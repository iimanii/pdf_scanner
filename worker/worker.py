import os
import time
import threading
import signal
import concurrent.futures
from datetime import datetime, timedelta
from shared.database import get_db_session, Task, init_database_url, increment_metric
from sqlalchemy import or_, and_
import json
from virustotal import VirusTotal
import shared.utils as utils

def log_execution_step(step, task_id=None, **kwargs):
    log_data = {
        "timestamp": datetime.utcnow().isoformat(),
        "step": step,
        "thread": threading.current_thread().name,
        **kwargs
    }
    if task_id:
        log_data["task_id"] = task_id
    print(json.dumps(log_data), flush=True)


class Worker:
    def __init__(self, threads=1):
        self.num_threads = threads
        self.running = True

        log_execution_step("worker_initialized", threads=threads)

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self.shutdown_handler)
        signal.signal(signal.SIGINT, self.shutdown_handler)

    def shutdown_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        signal_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        log_execution_step("shutdown_signal_received", signal=signal_name, signum=signum)
        print("Received shutdown signal, stopping worker...")
        self.running = False

    def claim_next_task(self):
        """Atomically claim next available task using skip_locked"""
        db = get_db_session()
        # Tasks are stale if heartbeat is older than 15 seconds
        stale_time = datetime.utcnow() - timedelta(seconds=15)

        try:
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
                log_execution_step("task_claimed", task.id,
                                   status=task.status,
                                   virustotal_id=task.virustotal_id,
                                   worker_heartbeat=task.worker_heartbeat.isoformat() if task.worker_heartbeat else None)

            return task, db
        except Exception as e:
            log_execution_step("task_claim_error", error=str(e), error_type=type(e).__name__)
            raise

    def worker_thread(self):
        """Individual worker thread function"""
        log_execution_step("worker_thread_started")

        while self.running:
            try:
                task, db = self.claim_next_task()

                try:
                    if task and self.running:
                        self.process_task(task, db)
                    elif self.running:
                        time.sleep(5)
                except Exception as e:
                    if task:
                        log_execution_step("task_processing_error", task.id,
                                           error=str(e), error_type=type(e).__name__)
                    else:
                        log_execution_step("worker_thread_error",
                                           error=str(e), error_type=type(e).__name__)
                finally:
                    try:
                        db.close()
                    except Exception as e:
                        log_execution_step("database_close_error",
                                           error=str(e), error_type=type(e).__name__)
            except Exception as e:
                log_execution_step("worker_thread_critical_error",
                                   error=str(e), error_type=type(e).__name__)
                # Sleep briefly before retrying to avoid tight error loops
                time.sleep(1)

        log_execution_step("worker_thread_stopped")

    def process_task(self, task, db):
        """Process task based on current state"""
        scanner = VirusTotal(os.getenv("VIRUSTOTAL_API_KEY"))

        try:
            if task.status == "PENDING":
                # Step 1: Upload to VirusTotal
                log_execution_step("upload_started", task.id, file_path=task.stored_file_path)

                if not os.path.exists(task.stored_file_path):
                    raise FileNotFoundError(f"File not found: {task.stored_file_path}")

                with open(task.stored_file_path, 'rb') as file:
                    file_content = file.read()

                if not utils.is_valid_pdf_content(file_content):
                    log_execution_step("file_not_pdf", task.id, file_path=task.stored_file_path)

                    task.status = "FAILED"
                    task.error_message = f"File not a valid pdf"
                    increment_metric('failed', db)
                    db.commit()
                    return

                analysis_id = scanner.upload_file(task.stored_file_path)
                log_execution_step("upload_completed", task.id, analysis_id=analysis_id)

                # Update task status
                task.status = "RUNNING"
                task.virustotal_id = analysis_id
                task.worker_heartbeat = datetime.utcnow()

                db.commit()

            elif task.status == "RUNNING" and task.virustotal_id:
                # Step 2: Check if analysis is complete
                analysis = scanner.get_analysis(task.virustotal_id)
                status = analysis['data']['attributes']['status']

                if status == 'completed':
                    # Save results and mark complete
                    report_path = f"/data/reports/{task.id}.json"
                    os.makedirs(os.path.dirname(report_path), exist_ok=True)

                    with open(report_path, 'w') as f:
                        json.dump(analysis, f, indent=2)

                    log_execution_step("task_completed", task.id,
                                       report_path=report_path,
                                       virustotal_url=f"https://www.virustotal.com/gui/file-analysis/{task.virustotal_id}")

                    task.status = "COMPLETED"
                    task.scan_report_path = report_path
                    task.virustotal_url = f"https://www.virustotal.com/gui/file-analysis/{task.virustotal_id}"
                    increment_metric('completed', db)
                    db.commit()

                    print(f"Task {task.id} completed")

                elif status in ['queued', 'running']:
                    # Still processing, update heartbeat and release
                    task.worker_heartbeat = datetime.utcnow()
                    db.commit()
                    print(f"Task {task.id} still processing: {status}", flush=True)

                elif status in ['cancelled', 'timeout', 'failure']:
                    # VirusTotal analysis failed
                    log_execution_step("analysis_failed", task.id,
                                       virustotal_status=status, reason="virustotal_analysis_failed")

                    task.status = "FAILED"
                    task.error_message = f"VirusTotal analysis {status}"
                    increment_metric('failed', db)
                    db.commit()
                    print(f"Task {task.id} failed with VirusTotal status: {status}", flush=True)

                else:
                    # Unknown status
                    log_execution_step("unknown_analysis_status", task.id, virustotal_status=status)

                    task.status = "FAILED"
                    task.error_message = f"Unknown VirusTotal status: {status}"
                    increment_metric('failed', db)
                    db.commit()
                    print(f"Task {task.id} failed with unknown status: {status}", flush=True)

            elif task.status == "RUNNING" and not task.virustotal_id:
                # Step 3: Handle corrupted state - reset to PENDING
                log_execution_step("corrupted_state_reset", task.id,
                                   reason="running_without_virustotal_id")

                print(f"Task {task.id} in RUNNING state but missing virustotal_id, resetting to PENDING")
                task.status = "PENDING"
                task.worker_heartbeat = datetime.utcnow()
                db.commit()

        except FileNotFoundError as e:
            log_execution_step("file_not_found_error", task.id,
                               error=str(e), file_path=getattr(task, 'stored_file_path', 'unknown'))

            task.status = "FAILED"
            task.error_message = f"File not found: {str(e)}"
            increment_metric('failed', db)
            db.commit()

        except Exception as e:
            log_execution_step("task_processing_exception", task.id,
                               error=str(e), error_type=type(e).__name__,
                               current_status=task.status)

            task.status = "FAILED"
            task.error_message = str(e)
            increment_metric('failed', db)
            db.commit()
            print(f"Task {task.id} failed: {e}", flush=True)

    def run(self):
        """Start multiple worker threads"""
        log_execution_step("worker_startup", threads=self.num_threads)
        print(f"Starting worker with {self.num_threads} threads")

        threads = []

        # Start all worker threads
        for i in range(self.num_threads):
            thread_name = f"Worker-{i + 1}"
            thread = threading.Thread(target=self.worker_thread, name=thread_name)
            thread.daemon = True
            threads.append(thread)
            thread.start()

        try:
            # Wait for all threads to complete
            for thread in threads:
                thread.join()
        except KeyboardInterrupt:
            log_execution_step("keyboard_interrupt_received")
            self.running = False
            print("Keyboard interrupt received, shutting down...")

        log_execution_step("worker_shutdown_complete")


if __name__ == "__main__":
    log_execution_step("application_startup")

    # from dotenv import load_dotenv
    # load_dotenv()

    api_key = os.getenv("VIRUSTOTAL_API_KEY")
    if not api_key:
        log_execution_step("startup_error", error="VIRUSTOTAL_API_KEY environment variable required")
        raise Exception("VIRUSTOTAL_API_KEY environment variable required")

    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")
    database = os.getenv("POSTGRES_DB")
    host = "postgres"  # Docker service name
    port = "5432"

    # Validate required environment variables
    if not all([user, password, database]):
        missing_vars = [var for var, val in
                        [("POSTGRES_USER", user), ("POSTGRES_PASSWORD", password), ("POSTGRES_DB", database)] if
                        not val]
        log_execution_step("startup_error", error="Missing required environment variables",
                           missing_variables=missing_vars)
        raise Exception("Missing required environment variables: POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB")

    url = f"postgresql://{user}:{password}@{host}:{port}/{database}"

    try:
        init_database_url(url)
        log_execution_step("database_initialized")
    except Exception as e:
        log_execution_step("database_initialization_error", error=str(e), error_type=type(e).__name__)
        raise

    reports_dir = "/data/reports"
    try:
        os.makedirs(reports_dir, exist_ok=True)
    except Exception as e:
        log_execution_step("reports_directory_creation_error",
                           error=str(e), error_type=type(e).__name__, reports_dir=reports_dir)
        raise

    num_threads = int(os.getenv("WORKER_THREADS", 1))

    try:
        worker = Worker(num_threads)
        worker.run()
    except Exception as e:
        log_execution_step("worker_run_error", error=str(e), error_type=type(e).__name__)
        raise
    finally:
        log_execution_step("application_shutdown")