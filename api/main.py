from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
import uvicorn
import os
import traceback
import json
from typing import List
from shared.database import get_db, get_db_session, Metric, Task, init_database_url, increment_metric
import shared.utils as utils
import asyncio
import asyncpg
import json
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("lifespan", flush=True)
    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")
    database = os.getenv("POSTGRES_DB")
    host = "postgres"  # Docker service name
    port = "5432"

    url = f"postgresql://{user}:{password}@{host}:{port}/{database}"

    init_database_url(url)
    listener_task  = asyncio.create_task(start_db_listener(url))

    yield

    # Shutdown
    listener_task.cancel()

app = FastAPI(title="PDF Scanner API", lifespan=lifespan)

UPLOAD_DIR = "/data/uploads"

# WebSocket Connection Manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except:
                disconnected.append(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.active_connections.remove(conn)


manager = ConnectionManager()


def format_task(task: Task) -> dict:
    """Convert Task object to dict for JSON serialization"""
    return {
        "id": task.id,
        "description": task.user_description,
        "filename": task.original_filename,
        "status": task.status,
        "file_size": utils.format_file_size(task.file_size_bytes),
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "error_message": task.error_message,
        "report_url": f"/data/reports/{task.id}.json" if task.scan_report_path else None,
        "virustotal_url": task.virustotal_url
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, db: Session = Depends(get_db)):
    await manager.connect(websocket)

    try:
        # Send initial tasks (latest 100)
        tasks = db.query(Task).order_by(Task.created_at.desc()).limit(100).all()
        await websocket.send_text(json.dumps({
            "type": "initial_tasks",
            "tasks": [format_task(task) for task in tasks]
        }))

        # Send initial metrics
        metrics = db.query(Metric).all()
        await websocket.send_text(json.dumps({
            "type": "initial_metrics",
            "metrics": {m.metric_name: m.metric_value for m in metrics}
        }))

        # Keep connection alive
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect(websocket)


@app.post("/upload")
async def upload_pdf(
        file: UploadFile = File(...),
        description: str = Form(...),
        db: Session = Depends(get_db)
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Clean the filename
    safe_filename = utils.clean_filename(file.filename)

    # Read file content into memory
    file_content = await file.read()

    # Check if it's a valid PDF (before saving)
    if not utils.is_valid_pdf_content(file_content):
        raise HTTPException(status_code=400, detail="File is not a valid PDF")

    # Check file size
    file_size = len(file_content)
    if utils.is_file_too_large(file_size):
        raise HTTPException(
            status_code=413,
            detail=f"File too large: {utils.format_file_size(file_size)}. Maximum: 50 MB"
        )

    # Everything looks good, now save the file
    unique_filename = utils.generate_unique_filename(safe_filename)
    file_path = os.path.join(UPLOAD_DIR, unique_filename)

    try:
        # Save file to disk
        with open(file_path, "wb") as f:
            f.write(file_content)

        # Calculate hash from content
        file_hash = utils.calculate_hash_from_content(file_content)

        # Check for duplicate hash in database
        existing_task = db.query(Task).filter(Task.file_hash == file_hash).first()
        if existing_task:
            if existing_task.status != "FAILED":
                # Clean up the file we just saved
                if os.path.exists(file_path):
                    os.remove(file_path)
                raise HTTPException(
                    status_code=409,
                    detail=f"File already exists. Task ID: {existing_task.id}"
                )

        # Save task to database
        new_task = Task(
            user_description=description,
            original_filename=file.filename,
            stored_file_path=file_path,
            file_hash=file_hash,
            file_size_bytes=file_size,
            status="PENDING"
        )
        db.add(new_task)
        increment_metric('submitted', db)

        db.commit()
        db.refresh(new_task)


        # Broadcast new task to WebSocket clients
        await manager.broadcast({
            "type": "new_task",
            "task": format_task(new_task)
        })

        return {
            "success": True,
            "message": "File uploaded successfully",
            "task_id": new_task.id,
            "user_filename": file.filename,
            "user_description": description,
            "file_hash": file_hash[:16],
            "file_size": utils.format_file_size(file_size),
            "status": "PENDING"
        }

    except HTTPException:
        raise
    except Exception as e:
        error_details = traceback.format_exc()
        print(f"❌ Error: {str(e)}")
        print(f"📍 Stack trace:\n{error_details}")

        # Clean up if something went wrong
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@app.get("/tasks")
async def get_tasks(db: Session = Depends(get_db)):
    """Get list of all tasks"""
    tasks = db.query(Task).order_by(Task.created_at.desc()).limit(100).all()
    return {
        "tasks": [format_task(task) for task in tasks]
    }


@app.get("/tasks/{task_id}")
async def get_task(task_id: int, db: Session = Depends(get_db)):
    """Get specific task details"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return format_task(task)


@app.get("/health")
async def health_check():
    """Check if API is working"""
    return {
        "status": "healthy",
        "upload_dir": UPLOAD_DIR,
        "virustotal_key": "configured" if os.getenv("VIRUSTOTAL_API_KEY") else "missing",
        "websocket_connections": len(manager.active_connections)
    }


@app.get("/scan-results/{task_id}")
async def get_scan_results(task_id: int, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != "COMPLETED":
        raise HTTPException(status_code=400, detail="Scan not completed yet")

    # Read the scan report
    try:
        with open(task.scan_report_path, 'r') as f:
            scan_data = json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Scan report not found")

    return {
        "task": format_task(task),
        "scan_results": scan_data
    }

@app.get("/metrics")
async def get_metrics(db: Session = Depends(get_db)):
    metrics = db.query(Metric).all()
    return {m.metric_name: m.metric_value for m in metrics}

@app.get("/")
async def root():
    """API root endpoint"""
    return {
        "message": "PDF Scanner API",
        "version": "1.0"
    }

async def notification_handler(connection, pid, channel, payload):
    print("notification update", flush=True)
    try:
        task_data = json.loads(payload)
        formatted_task = format_task_from_dict(task_data)
        await manager.broadcast({
            "type": "task_update",
            "task": formatted_task
        })
    except Exception as e:
        print(f"Notification error: {e}", flush=True)

async def metrics_notification_handler(connection, pid, channel, payload):
    print("metric update", flush=True)
    db = get_db_session()
    try:
        metrics = db.query(Metric).all()
        await manager.broadcast({
            "type": "metrics_update",
            "metrics": {m.metric_name: m.metric_value for m in metrics}
        })
    except Exception as e:
        print(f"metric update error: {e}", flush=True)
    finally:
        db.close()

async def start_db_listener(url):
    conn = await asyncpg.connect(url)
    await conn.add_listener('task_updates', notification_handler)
    await conn.add_listener('metrics_updates', metrics_notification_handler)
    print("task updates listener started", flush=True)
    await asyncio.Event().wait()

def format_task_from_dict(task_data):
    return {
        "id": task_data["id"],
        "description": task_data["user_description"],
        "filename": task_data["original_filename"],
        "status": task_data["status"],
        "file_size": utils.format_file_size(task_data["file_size_bytes"]),
        "created_at": task_data["created_at"],
        "error_message": task_data.get("error_message"),
        "report_url": f"/data/reports/{task_data['id']}.json" if task_data.get("scan_report_path") else None,
        "virustotal_url": task_data.get("virustotal_url")
    }

if __name__ == "__main__":
    utils.create_directory(UPLOAD_DIR)

    # Get PostgreSQL connection details from environment variables
    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")
    database = os.getenv("POSTGRES_DB")

    # Validate required environment variables
    if not all([user, password, database]):
        raise Exception("Missing required environment variables: POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB")

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
