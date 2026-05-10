"""
MinIO storage service — file upload, download, presigned URLs.
"""

import io
from datetime import timedelta
from typing import IO, Optional

from loguru import logger
from minio import Minio
from minio.error import S3Error

from app.config import settings


class StorageService:
    """S3-compatible object storage via MinIO."""

    def __init__(self):
        self._client: Optional[Minio] = None
        self._presign_client: Optional[Minio] = None

    @property
    def client(self) -> Minio:
        if self._client is None:
            self._client = Minio(
                endpoint=settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
            )
        return self._client

    @property
    def presign_client(self) -> Minio:
        """Separate client using the public endpoint so presigned URL signatures match.

        Pre-seeds the bucket region to avoid a connectivity check against the public
        endpoint (which may be unreachable from inside the Docker container).
        MinIO always uses us-east-1 by default.
        """
        if self._presign_client is None:
            public = settings.minio_public_endpoint or settings.minio_endpoint
            client = Minio(
                endpoint=public,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
            )
            client._region_map[settings.minio_bucket] = "us-east-1"
            self._presign_client = client
        return self._presign_client

    async def ensure_bucket(self):
        """Create the default bucket if it doesn't exist."""
        bucket = settings.minio_bucket
        try:
            if not self.client.bucket_exists(bucket):
                self.client.make_bucket(bucket)
                logger.info(f"Created MinIO bucket: {bucket}")
            else:
                logger.debug(f"MinIO bucket already exists: {bucket}")
        except S3Error as e:
            logger.error(f"Failed to ensure MinIO bucket: {e}")
            raise

    def upload_file(
        self,
        object_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload a file to MinIO. Returns the object key."""
        bucket = settings.minio_bucket
        self.client.put_object(
            bucket_name=bucket,
            object_name=object_name,
            data=io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        logger.debug(f"Uploaded {object_name} to MinIO ({len(data)} bytes)")
        return object_name

    def download_file(self, object_name: str) -> bytes:
        """Download a file from MinIO and return its bytes."""
        bucket = settings.minio_bucket
        response = None
        try:
            response = self.client.get_object(bucket, object_name)
            return response.read()
        finally:
            if response:
                response.close()
                response.release_conn()

    def upload_stream(
        self,
        object_name: str,
        stream: IO[bytes],
        length: int,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload from a stream."""
        bucket = settings.minio_bucket
        self.client.put_object(
            bucket_name=bucket,
            object_name=object_name,
            data=stream,  # type: ignore[arg-type]
            length=length,
            content_type=content_type,
        )
        return object_name

    async def upload_stream_async(
        self,
        object_name: str,
        stream: IO[bytes],
        length: int,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Non-blocking wrapper for upload_stream using asyncio.to_thread."""
        import asyncio
        return await asyncio.to_thread(
            self.upload_stream, object_name, stream, length, content_type
        )

    def get_presigned_url(
        self,
        object_name: str,
        expiry_hours: Optional[int] = None,
    ) -> str:
        """Generate a presigned download URL using the public-facing endpoint.

        Uses a dedicated client configured with minio_public_endpoint so the
        HMAC signature is computed against the browser-accessible hostname.
        """
        hours = expiry_hours or settings.minio_presign_expiry_hours
        return self.presign_client.presigned_get_object(
            bucket_name=settings.minio_bucket,
            object_name=object_name,
            expires=timedelta(hours=hours),
        )

    def delete_object(self, object_name: str):
        """Delete a file from MinIO."""
        self.client.remove_object(settings.minio_bucket, object_name)
        logger.debug(f"Deleted {object_name} from MinIO")

    def list_objects(self, prefix: str, recursive: bool = True):
        """List all objects under a given prefix."""
        return self.client.list_objects(settings.minio_bucket, prefix=prefix, recursive=recursive)

    def delete_prefix(self, prefix: str):
        """Delete all objects with a given prefix (e.g. a source's files)."""
        objects = self.client.list_objects(settings.minio_bucket, prefix=prefix, recursive=True)
        for obj in objects:
            if obj.object_name:
                self.client.remove_object(settings.minio_bucket, obj.object_name)
        logger.debug(f"Deleted all objects with prefix: {prefix}")

    def copy_object(self, src_key: str, dest_key: str):
        """Copy a single object within the same bucket."""
        from minio.commonconfig import CopySource
        bucket = settings.minio_bucket
        self.client.copy_object(
            bucket,
            dest_key,
            CopySource(bucket, src_key),
        )

    def copy_prefix(self, src_prefix: str, dest_prefix: str):
        """Copy all objects from one prefix to another (recursively)."""
        bucket = settings.minio_bucket
        
        # Check if src_prefix is a specific file using stat_object (more reliable)
        is_file = False
        try:
            self.client.stat_object(bucket, src_prefix)
            is_file = True
        except Exception:
            is_file = False
        
        if is_file:
            # Single file copy - do NOT add slashes
            self.copy_object(src_prefix, dest_prefix)
            logger.debug(f"Copied file {src_prefix} to {dest_prefix}")
            return

        # Directory copy - MUST ensure trailing slashes to avoid partial matches
        src_p = src_prefix if src_prefix.endswith("/") else f"{src_prefix}/"
        dest_p = dest_prefix if dest_prefix.endswith("/") else f"{dest_prefix}/"
        
        # List all objects under the folder prefix
        objects = self.client.list_objects(bucket, prefix=src_p, recursive=True)
        count = 0
        for obj in objects:
            rel_path = obj.object_name.replace(src_p, "", 1)
            dest_key = f"{dest_p}{rel_path}"
            self.copy_object(obj.object_name, dest_key)
            count += 1
        
        logger.info(f"Copied folder content ({count} objects) from {src_p} to {dest_p}")
    
    def move_prefix(self, src_prefix: str, dest_prefix: str):
        """Move all objects from one prefix to another (recursively), then delete source."""
        bucket = settings.minio_bucket
        
        # Determine if it's a file or folder before moving
        is_file = False
        try:
            self.client.stat_object(bucket, src_prefix)
            is_file = True
        except Exception:
            is_file = False

        self.copy_prefix(src_prefix, dest_prefix)
        
        if is_file:
            self.delete_object(src_prefix)
        else:
            # Delete folder with trailing slash to be safe
            src_p = src_prefix if src_prefix.endswith("/") else f"{src_prefix}/"
            self.delete_prefix(src_p)
            
        logger.info(f"Moved {src_prefix} to {dest_prefix}")

    def calculate_prefix_hash(self, prefix: str) -> str:
        """
        Calculate a unique hash for all objects under a prefix.
        Uses object names and ETags to detect any content or structure change.
        """
        import hashlib
        bucket = settings.minio_bucket
        p = prefix if prefix.endswith("/") else f"{prefix}/"
        
        objects = self.client.list_objects(bucket, prefix=p, recursive=True)
        # Sort objects by name to ensure stable hash
        sorted_objects = sorted(objects, key=lambda x: x.object_name)
        
        hasher = hashlib.sha256()
        for obj in sorted_objects:
            rel_path = obj.object_name.replace(p, "", 1)
            # Combine path and etag
            hasher.update(rel_path.encode("utf-8"))
            hasher.update(obj.etag.encode("utf-8"))
            
        return hasher.hexdigest()


# Singleton
storage_service = StorageService()
