import os
import time
import threading
import concurrent.futures
from datetime import datetime, timedelta
from shared.database import get_db_session, Task, init_database_url
from sqlalchemy import or_, and_
import json
from virustotal import VirusTotal

class Worker:
    def __init__(self, threads=1):
        self.num_threads = threads
        self.running = True

    def claim_next_task(self):
        """Atomically claim next available task using skip_locked"""
        db = get_db_session()
        # Tasks are stale if heartbeat is older than 15 seconds
        stale_time = datetime.utcnow() - timedelta(seconds=15)

        task = db.query(Task).filter(
            or_(
                Task.status == "PENDING",
                and_(
                    Task.status == "RUNNING",
                    or_(
                        Task.worker_heartbeat.is_(None),
                        Task.worker_heartbeat < stale_time
                    )
                )
            )
        ).with_for_update(skip_locked=True).first()

        if task:
            print(f"Thread {threading.current_thread().name} claimed task {task.id}", flush=True)

        return task, db
    
    def worker_thread(self):
        """Individual worker thread function"""
        while self.running:
            print("Claiming next task")
            task, db = self.claim_next_task()

            try:
                if task:
                    print(f"Found task, processing {task.id}", flush=True)
                    self.process_task(task, db)
                else:
                    time.sleep(5)
            finally:
                db.close()

    def process_task(self, task, db):
        """Process task based on current state"""
        scanner = VirusTotal(os.getenv("VIRUSTOTAL_API_KEY"))

        try:
            if task.status == "PENDING":
                # Step 1: Upload to VirusTotal
                analysis_id = scanner.upload_file(task.stored_file_path)

                task.status = "RUNNING"
                task.virustotal_id = analysis_id
                task.worker_heartbeat = datetime.utcnow()
                db.commit()

                print(f"Task {task.id} uploaded, analysis ID: {analysis_id}", flush=True)

            elif task.status == "RUNNING" and task.virustotal_id:
                # Step 2: Check if analysis is complete
                analysis = scanner.get_analysis(task.virustotal_id)
                status = analysis['data']['attributes']['status']

                if status == 'completed':
                    # Save results and mark complete
                    report_path = f"/data/reports/{task.id}.json"
                    with open(report_path, 'w') as f:
                        json.dump(analysis, f, indent=2)

                    task.status = "COMPLETED"
                    task.scan_report_path = report_path
                    task.virustotal_url = f"https://www.virustotal.com/gui/file-analysis/{task.virustotal_id}"
                    db.commit()

                    print(f"Task {task.id} completed")
                elif status in ['queued', 'running']:
                    # Still processing, update heartbeat and release
                    task.worker_heartbeat = datetime.utcnow()
                    db.commit()
                    print(f"Task {task.id} still processing: {status}", flush=True)
                elif status in ['cancelled', 'timeout', 'failure']:
                    # VirusTotal analysis failed
                    task.status = "FAILED"
                    task.error_message = f"VirusTotal analysis {status}"
                    db.commit()
                    print(f"Task {task.id} failed with VirusTotal status: {status}", flush=True)
                else:
                    # Unknown status
                    task.status = "FAILED"
                    task.error_message = f"Unknown VirusTotal status: {status}"
                    db.commit()
                    print(f"Task {task.id} failed with unknown status: {status}", flush=True)

            elif task.status == "RUNNING" and not task.virustotal_id:
                # Step 3: Handle corrupted state - reset to PENDING
                print(f"Task {task.id} in RUNNING state but missing virustotal_id, resetting to PENDING")
                task.status = "PENDING"
                task.worker_heartbeat = datetime.utcnow()
                db.commit()

        except Exception as e:
            task.status = "FAILED"
            task.error_message = str(e)
            db.commit()
            print(f"Task {task.id} failed: {e}", flush=True)
    
    def run(self):
        """Start multiple worker threads"""
        print(f"Starting worker with {self.num_threads} threads")

        threads = []

        # Start all worker threads
        for i in range(self.num_threads):
            thread = threading.Thread(target=self.worker_thread, name=f"Worker-{i + 1}")
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

if __name__ == "__main__":
    #from dotenv import load_dotenv
    #load_dotenv()

    api_key = os.getenv("VIRUSTOTAL_API_KEY")
    if not api_key:
        raise Exception("VIRUSTOTAL_API_KEY environment variable required")
	
    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")
    database = os.getenv("POSTGRES_DB")
    host = "postgres"  # Docker service name
    port = "5432"

    # Validate required environment variables
    if not all([user, password, database]):
        raise Exception("Missing required environment variables: POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB")
	
    url = f"postgresql://{user}:{password}@{host}:{port}/{database}"

    init_database_url(url)
	
    reports_dir = "/data/reports"
    os.makedirs(reports_dir, exist_ok=True)
    
    num_threads = int(os.getenv("WORKER_THREADS", 1))
    worker = Worker(num_threads)
    worker.run()