import hashlib
import os
from datetime import datetime

def calculate_hash_from_content(file_content: bytes) -> str:
    """Calculate SHA256 hash from file content"""
    return hashlib.sha256(file_content).hexdigest()

def is_valid_pdf_content(file_content: bytes) -> bool:
    """Check if file content is a valid PDF"""
    return file_content.startswith(b'%PDF')

def generate_unique_filename(original_filename: str) -> str:
    """Generate unique filename with timestamp"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_{original_filename}"

def create_directory(directory: str) -> None:
    """Create directory if it doesn't exist"""
    os.makedirs(directory, exist_ok=True)

def format_file_size(size_bytes: int) -> str:
    """Convert bytes to MB"""
    mb = size_bytes / (1024 * 1024)
    return f"{mb:.1f} MB"

def is_file_too_large(file_size: int) -> bool:
    """Check if file is larger than 50MB"""
    max_size = 50 * 1024 * 1024  # 50MB in bytes
    return file_size > max_size

def clean_filename(filename: str) -> str:
    """Remove bad characters from filename"""
    bad_chars = ['/', '\\', '<', '>', ':', '"', '|', '?', '*']
    
    for char in bad_chars:
        filename = filename.replace(char, '_')
    
    name, ext = os.path.splitext(filename)
    if len(name) > 100:
        name = name[:100]
    
    return f"{name}{ext}"