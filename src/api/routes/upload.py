from fastapi import APIRouter, UploadFile
from minio import Minio
import uuid

router = APIRouter()

minio_client = Minio(
    "minio:9000",
    access_key="minioadmin",
    secret_key="minioadmin",
    secure=False
)

BUCKET = "photos"

@router.post("/")
async def upload_photo(file: UploadFile):
    if not minio_client.bucket_exists(BUCKET):
        minio_client.make_bucket(BUCKET)

    filename = f"{uuid.uuid4()}.jpg"
    content = await file.read()

    minio_client.put_object(
        BUCKET,
        filename,
        data=content,
        length=len(content),
        content_type="image/jpeg"
    )

    return {"url": f"http://localhost:9000/{BUCKET}/{filename}"}
