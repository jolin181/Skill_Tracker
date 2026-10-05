"""
app/modules/domains/syllabus_service.py
---------------------------------------
Business logic for syllabus upload, PDF processing, and retrieval.

Responsibilities:
- PDF file validation (size, type)
- PDF text extraction
- Text normalization
- Database persistence with version management
- Syllabus retrieval for AI consumption

Cross-module calls: None - domains is a leaf dependency.
Does NOT import other module models directly.
"""

import re
from datetime import datetime
from io import BytesIO
from typing import BinaryIO, Tuple

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.exceptions import NotFoundError
from app.modules.domains.models import Track, TrackSyllabus


# ── PDF Validation ─────────────────────────────────────────────────────────

def validate_pdf_file(file_content: bytes, file_name: str) -> None:
    """
    Validate that the uploaded file is a valid PDF.

    Checks:
    1. File size (max 10MB)
    2. PDF magic number (header)
    3. File extension
    4. Minimum size

    Raises ValueError with descriptive message on failure.
    """
    MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10MB

    # Check size
    if len(file_content) > MAX_SIZE_BYTES:
        raise ValueError(
            f"File size ({len(file_content)} bytes) exceeds maximum allowed (10MB)"
        )

    # Check minimum size
    if len(file_content) < 100:
        raise ValueError("File is too small to be a valid PDF")

    # Check PDF magic number (PDF files start with %PDF-)
    if not file_content.startswith(b'%PDF-'):
        raise ValueError("File is not a valid PDF (invalid header)")

    # Check file extension
    if not file_name.lower().endswith('.pdf'):
        raise ValueError("File must have .pdf extension")


# ── PDF Text Extraction ────────────────────────────────────────────────────

def extract_text_from_pdf(file_content: bytes) -> Tuple[str, int]:
    """
    Extract text content from PDF file.

    Returns:
        (extracted_text, page_count)

    Raises:
        ValueError: If PDF cannot be read, is corrupt, or is a scanned image
        ImportError: If PyPDF2 is not installed

    Implementation Note:
        Uses PyPDF2 for extraction.
        Does NOT support OCR for scanned PDFs.
    """
    try:
        import PyPDF2
    except ImportError:
        raise ImportError(
            "PyPDF2 is required for PDF text extraction. "
            "Please add 'PyPDF2>=3.0.0' to requirements.txt"
        )

    try:
        pdf_reader = PyPDF2.PdfReader(BytesIO(file_content))
        page_count = len(pdf_reader.pages)

        if page_count == 0:
            raise ValueError("PDF has no pages")

        # Extract text from all pages
        extracted_text = ""
        pages_with_text = 0

        for page_num, page in enumerate(pdf_reader.pages, 1):
            try:
                text = page.extract_text()
                if text and text.strip():
                    extracted_text += f"\n\n--- Page {page_num} ---\n\n"
                    extracted_text += text
                    pages_with_text += 1
            except Exception as e:
                # Log warning but continue with other pages
                print(f"Warning: Could not extract text from page {page_num}: {e}")

        # Validate we got some text
        extracted_text = extracted_text.strip()
        if not extracted_text or len(extracted_text) < 50:
            raise ValueError(
                "No text could be extracted from PDF. "
                "This may be a scanned image or protected PDF. "
                "OCR is not supported. "
                f"Pages processed: {page_count}, pages with text: {pages_with_text}"
            )

        return extracted_text, page_count

    except PyPDF2.errors.PdfReadError as e:
        raise ValueError(f"Failed to read PDF (file may be corrupted): {str(e)}")
    except ImportError:
        # Re-raise ImportError as-is
        raise
    except ValueError:
        # Re-raise our own ValueError as-is
        raise
    except Exception as e:
        raise ValueError(f"PDF text extraction failed: {str(e)}")


# ── Text Normalization ─────────────────────────────────────────────────────

def normalize_text(raw_text: str) -> str:
    """
    Clean and normalize extracted text.

    Steps:
    1. Remove control characters (except newline/tab)
    2. Normalize whitespace per line
    3. Remove excessive blank lines (max 2 consecutive)
    4. Preserve structure (don't over-normalize for AI)

    This is intentionally light - we want to preserve
    the original structure for AI processing.
    """
    # Remove control characters except newline and tab
    text = ''.join(char for char in raw_text if ord(char) >= 32 or char in '\n\t')

    # Normalize multiple spaces to single space (per line)
    lines = text.split('\n')
    lines = [re.sub(r' +', ' ', line.strip()) for line in lines]

    # Remove excessive blank lines (max 2 consecutive)
    cleaned_lines = []
    blank_count = 0
    for line in lines:
        if line:
            cleaned_lines.append(line)
            blank_count = 0
        else:
            blank_count += 1
            if blank_count <= 2:
                cleaned_lines.append(line)

    return '\n'.join(cleaned_lines).strip()


# ── Database Operations ────────────────────────────────────────────────────

async def upload_syllabus(
    track_id: int,
    uploaded_by: int,
    file_content: bytes,
    file_name: str,
    notes: str | None,
    db: AsyncSession
) -> dict:
    """
    Upload and process a syllabus PDF.

    Steps:
    1. Verify track exists
    2. Validate PDF file
    3. Extract text from PDF
    4. Normalize text
    5. Mark existing syllabus as replaced
    6. Store new syllabus as current
    7. Return metadata

    Raises:
        ValueError: If validation or extraction fails
        NotFoundError: If track doesn't exist
        ImportError: If PyPDF2 is not available
    """
    # 1. Verify track exists
    track = await db.get(Track, track_id)
    if not track:
        raise NotFoundError(f"Track {track_id} not found")

    # 2. Validate PDF file (raises ValueError on error)
    validate_pdf_file(file_content, file_name)

    # 3. Extract text from PDF (raises ValueError on error)
    raw_text, page_count = extract_text_from_pdf(file_content)

    # 4. Normalize text
    normalized_text = normalize_text(raw_text)

    # 5. Mark existing current syllabus as replaced (atomic update)
    await db.execute(
        update(TrackSyllabus)
        .where(
            TrackSyllabus.track_id == track_id,
            TrackSyllabus.is_current == True
        )
        .values(
            is_current=False,
            status='replaced',
            replaced_at=datetime.utcnow()
        )
    )

    # 6. Create new syllabus record
    new_syllabus = TrackSyllabus(
        track_id=track_id,
        uploaded_by=uploaded_by,
        file_name=file_name,
        file_size_bytes=len(file_content),
        page_count=page_count,
        raw_text=normalized_text,
        is_current=True,
        status='active',
        notes=notes
    )
    db.add(new_syllabus)
    await db.commit()
    await db.refresh(new_syllabus)

    # 7. Return metadata
    return {
        "syllabus_id": new_syllabus.id,
        "track_id": new_syllabus.track_id,
        "file_name": new_syllabus.file_name,
        "uploaded_at": new_syllabus.uploaded_at,
        "page_count": new_syllabus.page_count,
        "extracted_text_length": len(normalized_text),
        "text_preview": normalized_text[:200] if normalized_text else ""
    }


async def get_current_syllabus(track_id: int, db: AsyncSession) -> dict:
    """
    Get the current active syllabus for a track.

    Returns full syllabus including raw_text for AI consumption.

    Raises:
        NotFoundError: If no current syllabus exists for track
    """
    result = await db.execute(
        select(TrackSyllabus)
        .options(joinedload(TrackSyllabus.track))
        .where(
            TrackSyllabus.track_id == track_id,
            TrackSyllabus.is_current == True
        )
    )
    syllabus = result.scalar_one_or_none()

    if not syllabus:
        raise NotFoundError(f"No syllabus found for track {track_id}")

    return {
        "syllabus_id": syllabus.id,
        "track_id": syllabus.track_id,
        "track_name": syllabus.track.name,
        "file_name": syllabus.file_name,
        "uploaded_by": syllabus.uploaded_by,
        "uploaded_at": syllabus.uploaded_at,
        "page_count": syllabus.page_count,
        "file_size_bytes": syllabus.file_size_bytes,
        "raw_text": syllabus.raw_text,  # Full text for AI
        "status": syllabus.status,
        "notes": syllabus.notes
    }


async def get_syllabus_metadata(track_id: int, db: AsyncSession) -> dict:
    """
    Get syllabus metadata WITHOUT the full text (lighter response).

    Useful for UI lists, dashboards, etc.

    Returns has_syllabus=False if no syllabus exists for track.
    """
    result = await db.execute(
        select(TrackSyllabus)
        .options(joinedload(TrackSyllabus.track))
        .where(
            TrackSyllabus.track_id == track_id,
            TrackSyllabus.is_current == True
        )
    )
    syllabus = result.scalar_one_or_none()

    if not syllabus:
        return {
            "has_syllabus": False,
            "track_id": track_id,
            "track_name": None
        }

    return {
        "has_syllabus": True,
        "syllabus_id": syllabus.id,
        "track_id": syllabus.track_id,
        "track_name": syllabus.track.name,
        "file_name": syllabus.file_name,
        "uploaded_at": syllabus.uploaded_at,
        "page_count": syllabus.page_count,
        "text_length": len(syllabus.raw_text) if syllabus.raw_text else 0
    }
