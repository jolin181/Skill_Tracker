"""
app/modules/domains/syllabus_router.py
---------------------------------------
Syllabus upload and retrieval endpoints for Track Owners.

All endpoints require Track Owner or Admin authorization.
Track Owners can only access their assigned track.

Endpoints:
- POST /api/v1/domains/{track_id}/syllabus/upload
- GET /api/v1/domains/{track_id}/syllabus
- GET /api/v1/domains/{track_id}/syllabus/metadata
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.exceptions import NotFoundError
from app.modules.domains import syllabus_service
from app.modules.domains.schemas import (
    SyllabusUploadResponse,
    SyllabusResponse,
    SyllabusMetadataResponse
)

router = APIRouter()


def verify_track_access(current_user: dict, track_id: int) -> None:
    """
    Verify user can access this track.
    - Admins can access any track
    - Domain owners can only access their role's track

    Raises HTTPException(403) if unauthorized.

    Pattern copied from analytics_router.py for consistency.
    """
    # Admin has full access
    if "admin" in current_user.get("roles", []):
        return

    # Check if user is a domain owner
    user = current_user.get("user")
    if user and hasattr(user, 'is_domain_owner') and user.is_domain_owner:
        # Check if this track is in their owned tracks
        if hasattr(user, 'owned_track_ids') and track_id in user.owned_track_ids:
            return

    # Unauthorized
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "TRACK_ACCESS_DENIED",
            "message": "You can only upload syllabus for your assigned track."
        }
    )


@router.post(
    "/{track_id}/syllabus/upload",
    response_model=SyllabusUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload syllabus PDF for a track",
    description="Upload a syllabus PDF file. Track Owners can only upload for their assigned track."
)
async def upload_syllabus(
    track_id: int,
    file: UploadFile = File(..., description="PDF file (max 10MB)"),
    notes: str | None = Form(None, description="Optional notes about this syllabus"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> SyllabusUploadResponse:
    """
    Upload a syllabus PDF for a track.

    **Authorization:** Admin or Track Owner for this track.

    **File Requirements:**
    - Must be a PDF file
    - Maximum size: 10MB
    - Must contain extractable text (not scanned images)

    **Returns:**
    - Syllabus ID
    - Upload metadata
    - Text extraction summary

    **Note:** If a syllabus already exists for this track, it will be
    replaced (old version is archived, not deleted).
    """
    # Verify authorization
    verify_track_access(current_user, track_id)

    # Read file content
    file_content = await file.read()

    # Validate content type
    if file.content_type and file.content_type != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file type. Only PDF files are accepted."
        )

    # Upload and process
    try:
        result = await syllabus_service.upload_syllabus(
            track_id=track_id,
            uploaded_by=current_user["id"],
            file_content=file_content,
            file_name=file.filename or "unknown.pdf",
            notes=notes,
            db=db
        )

        return SyllabusUploadResponse(
            success=True,
            message="Syllabus uploaded and processed successfully",
            **result
        )

    except ValueError as e:
        # PDF validation or extraction error
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )
    except ImportError as e:
        # PyPDF2 not installed
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PDF processing library not available. Please contact administrator."
        )
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.get(
    "/{track_id}/syllabus",
    response_model=SyllabusResponse,
    summary="Get current syllabus for a track",
    description="Retrieve the current active syllabus including full extracted text."
)
async def get_syllabus(
    track_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> SyllabusResponse:
    """
    Get the current active syllabus for a track.

    **Authorization:** Admin or Track Owner for this track.

    **Returns:**
    - Full syllabus data including extracted text
    - Upload metadata
    - Uploader information

    **Use Case:**
    This endpoint is used by the AI Question Generation workflow
    to retrieve syllabus text for question generation.
    """
    verify_track_access(current_user, track_id)

    try:
        syllabus = await syllabus_service.get_current_syllabus(track_id, db)
        return SyllabusResponse(**syllabus)
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.get(
    "/{track_id}/syllabus/metadata",
    response_model=SyllabusMetadataResponse,
    summary="Get syllabus metadata (without full text)",
    description="Lightweight endpoint for UI dashboards."
)
async def get_syllabus_metadata(
    track_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> SyllabusMetadataResponse:
    """
    Get syllabus metadata without the full text content.

    **Authorization:** Admin or Track Owner for this track.

    **Returns:**
    - Lightweight metadata (no raw_text field)
    - Suitable for UI lists and dashboards
    - has_syllabus flag indicates if syllabus exists
    """
    verify_track_access(current_user, track_id)

    metadata = await syllabus_service.get_syllabus_metadata(track_id, db)
    return SyllabusMetadataResponse(**metadata)
