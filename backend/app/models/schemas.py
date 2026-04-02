from datetime import datetime
from typing import Optional, List, Literal, Any, Dict
from pydantic import BaseModel, Field


class JobCreate(BaseModel):
    """Schema for creating a new job"""
    source_type: Literal["upload", "url"]
    url: Optional[str] = None


class LogEntry(BaseModel):
    """Schema for a processing log entry"""
    timestamp: str
    phase: str
    status: str
    message: str
    duration_ms: Optional[int] = None
    details: Optional[Dict[str, Any]] = None


class JobProgress(BaseModel):
    """Schema for job progress updates"""
    status: str
    progress: int
    current_step: Optional[str] = None


class JobSummary(BaseModel):
    """Schema for job summary data"""
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[str] = None
    summary_text: Optional[str] = None
    cost: float = 0.0


class JobResponse(BaseModel):
    """Schema for job response"""
    id: str
    source_type: str
    original_filename: Optional[str] = None
    status: str
    progress: int
    current_step: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None

    class Config:
        from_attributes = True


class JobDetailResponse(JobResponse):
    """Schema for detailed job response including summary"""
    summary: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[str] = None
    cost: float = 0.0
    logs: Optional[List[LogEntry]] = None

    class Config:
        from_attributes = True


class JobLogsResponse(BaseModel):
    """Schema for job logs response"""
    job_id: str
    logs: List[LogEntry]


class JobListResponse(BaseModel):
    """Schema for list of jobs"""
    jobs: List[JobResponse]
    total: int


class CostReport(BaseModel):
    """Schema for cost report"""
    total_jobs: int
    completed_jobs: int
    total_cost: float
    jobs: List[dict]


class URLSubmission(BaseModel):
    """Schema for URL submission"""
    url: str = Field(..., description="YouTube or direct video URL")


class HealthResponse(BaseModel):
    """Schema for health check response"""
    status: str
    version: str = "1.0.0"


class ErrorResponse(BaseModel):
    """Schema for error responses"""
    detail: str
