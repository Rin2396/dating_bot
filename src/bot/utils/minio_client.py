from minio import Minio
from io import BytesIO
import os
from io import BytesIO
from aiogram.types import BufferedInputFile


MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET_NAME = os.getenv("MINIO_BUCKET_NAME", "profile-photos")
MINIO_PUBLIC_URL = os.getenv("MINIO_PUBLIC_URL", "http://localhost:9000")


minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False
)


def upload_photo(photo_bytes: bytes) -> str:
    from uuid import uuid4

    filename = f"user_photos/{uuid4().hex}.jpg"

    if not minio_client.bucket_exists(MINIO_BUCKET_NAME):
        minio_client.make_bucket(MINIO_BUCKET_NAME)

    minio_client.put_object(
        MINIO_BUCKET_NAME,
        filename,
        data=BytesIO(photo_bytes),
        length=len(photo_bytes),
        content_type="image/jpeg"
    )

    public_url = f"{MINIO_PUBLIC_URL}/{MINIO_BUCKET_NAME}/{filename}"
    return public_url


def get_photo(user_id: str) -> BytesIO | None:
    object_name = f"user_photos/{user_id}.jpg"

    try:
        response = minio_client.get_object(
            bucket_name=MINIO_BUCKET_NAME,
            object_name=object_name
        )
        photo_file = BytesIO(response.read())
        response.close()
        response.release_conn()
        return photo_file
    except Exception:
        return None

async def get_photo_from_minio(photo_url: str) -> BufferedInputFile | None:
    """
    Скачать фото из MinIO по URL и вернуть как файл для Telegram.
    """
    try:
        parts = photo_url.split('/')
        bucket_index = parts.index(MINIO_BUCKET_NAME)
        object_name = '/'.join(parts[bucket_index + 1:])

        response = minio_client.get_object(
            bucket_name=MINIO_BUCKET_NAME,
            object_name=object_name
        )
        photo_bytes = BytesIO(response.read())
        response.close()
        response.release_conn()

        return BufferedInputFile(photo_bytes.read(), filename=object_name.split('/')[-1])
    except Exception as e:
        print(f"Ошибка при загрузке фото из MinIO: {e}")
        return None