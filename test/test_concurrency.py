import threading
import time
import os
from dotenv import load_dotenv
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
from shared.database import get_db_session, init_database_url


Base = declarative_base()

class TestJob(Base):
    __tablename__ = "test_jobs"

    id = Column(Integer, primary_key=True)
    status = Column(String(20), default="PENDING")
    worker_id = Column(String(10))
    created_at = Column(DateTime, default=datetime.utcnow)


def create_test_data():
    db = get_db_session()
    db.query(TestJob).delete()

    for i in range(4):
        job = TestJob(status="PENDING")
        db.add(job)

    db.commit()
    db.close()
    print("Created 3 test jobs")


def claim_task_bad(worker_id):
    """BAD: Race condition - multiple workers can claim same task"""
    db = get_db_session()

    try:
        task = db.query(TestJob).filter(TestJob.status == "PENDING").first()

        if task:
            print(f"Worker {worker_id} found job {task.id}")
            time.sleep(0.1)  # Creates race condition

            task.status = "RUNNING"
            task.worker_id = worker_id
            db.commit()
            print(f"Worker {worker_id} CLAIMED job {task.id}")
            return task.id

    except Exception as e:
        print(f"Worker {worker_id} error: {e}")
        db.rollback()
    finally:
        db.close()

    return None


def claim_task_good(worker_id):
    """GOOD: Atomic with skip_locked - no race condition"""
    db = get_db_session()

    try:
        task = db.query(TestJob).filter(TestJob.status == "PENDING").with_for_update(skip_locked=True).first()

        if task:
            task.status = "RUNNING"
            task.worker_id = worker_id
            db.commit()
            print(f"Worker {worker_id} claimed job {task.id}")
            return task.id

    except Exception as e:
        print(f"Worker {worker_id} error: {e}")
        db.rollback()
    finally:
        db.close()

    return None


def test_race_condition():
    """Show race condition with bad implementation"""
    print("=== TESTING RACE CONDITION (BAD) ===")

    results = {}
    threads = []

    def worker(worker_id):
        results[worker_id] = claim_task_bad(worker_id)

    for i in range(3):
        t = threading.Thread(target=worker, args=(f"W{i + 1}",))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    print(f"Results: {results}")
    print("^ Multiple workers likely claimed the same job!")


def test_skip_locked():
    """Show proper implementation with skip_locked"""
    print("\n=== TESTING SKIP_LOCKED (GOOD) ===")

    results = {}
    threads = []

    def worker(worker_id):
        results[worker_id] = claim_task_good(worker_id)

    for i in range(3):
        t = threading.Thread(target=worker, args=(f"W{i + 1}",))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    print(f"Results: {results}")
    print("^ Each worker gets different job (or None)")


if __name__ == "__main__":
    # Load .env file
    load_dotenv()

    POSTGRES_USER = os.getenv("POSTGRES_USER")
    POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")
    POSTGRES_DB = os.getenv("POSTGRES_DB")
    POSTGRES_HOST = "postgres"

    init_database_url(f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:5432/{POSTGRES_DB}")

    from shared.database import engine
    Base.metadata.create_all(engine)
    create_test_data()

    test_race_condition()  # Shows the problem
    test_skip_locked()  # Shows the solution