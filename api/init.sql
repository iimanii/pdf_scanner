-- PDF Scanner Database Schema
CREATE TABLE IF NOT EXISTS tasks (
    id SERIAL PRIMARY KEY,
    user_description VARCHAR(500) NOT NULL,         -- User's description of what they're scanning
    original_filename VARCHAR(255) NOT NULL,   -- What the user uploaded (report.pdf)
    stored_file_path VARCHAR(500) NOT NULL,    -- Where we saved it (/app/data/uploads/hash_report.pdf)
    file_hash VARCHAR(64) NOT NULL,            -- SHA256 for duplicate detection
    file_size_bytes INTEGER NOT NULL,          -- File size in bytes
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    error_message TEXT,
    scan_report_path VARCHAR(500),             -- Path to JSON scan results
    virustotal_id VARCHAR(100),
    virustotal_url VARCHAR(500),
    worker_heartbeat TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for faster queries
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_updated_at ON tasks(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_hash ON tasks(file_hash);

-- Notify api about updates [pg_notify] with full row
CREATE OR REPLACE FUNCTION notify_task_change()
RETURNS trigger AS $$
BEGIN
    RAISE NOTICE 'Trigger fired for task ID: %', NEW.id;

    PERFORM pg_notify('task_updates', row_to_json(NEW)::text);

    RAISE NOTICE 'Sent notification: %', row_to_json(NEW)::text;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Actual trigger when stuff changes in the table
CREATE TRIGGER task_update_trigger
    AFTER UPDATE ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION notify_task_change();