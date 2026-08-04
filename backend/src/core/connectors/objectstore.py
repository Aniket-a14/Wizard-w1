"""S3 and anything that speaks its API.

The object-storage third of the reference set: MinIO, Cloudflare R2, Backblaze B2
and S3 itself are the same connector with a different endpoint, which is the
point. It proves the interface holds for a source whose "tables" are files rather
than a catalog.

An object store is the one reference kind where the target names a *file format*
as much as a location, so the read delegates to pandas by extension rather than
inventing a second loader beside ``ingest/loader.py``.
"""

from __future__ import annotations

import io
from typing import Any

import pandas as pd

from src.config import settings

from .base import DEFAULT_SAMPLE_ROWS, refuse_write
from .registry import ConnectorKind, register
from .spec import ConnectionSchema, ConnectionSpec, ConnectorError, DriverMissing, TargetInfo


#: Objects the connector will try to read. Anything else in the bucket is listed
#: by `discover` but not offered as readable -- a bucket usually holds far more
#: than its tabular files, and silently trying to parse a JPEG as CSV is worse
#: than saying which objects are candidates.
READABLE_SUFFIXES = (".csv", ".tsv", ".json", ".jsonl", ".ndjson", ".parquet", ".feather")

#: How many objects `discover` lists. A bucket can hold millions, and enumerating
#: all of them to populate a picker is a bill as well as a wait.
LIST_LIMIT = 500


def _boto3() -> Any:
    try:
        import boto3
    except ImportError as exc:
        raise DriverMissing("objectstore", "boto3") from exc
    return boto3


class ObjectStoreConnector:
    """An S3-compatible bucket wearing the ``Connector`` interface."""

    def __init__(self, spec: ConnectionSpec, secret: str = ""):
        self.spec = spec
        self._secret = secret
        self._client: Any = None

    # ------------------------------------------------------------------ #
    def _bucket(self) -> str:
        bucket = str(self.spec.options.get("bucket") or "").strip()
        if not bucket:
            raise ConnectorError(
                "This connection names no bucket.",
                detail="Set the bucket this connection should read from.",
            )
        return bucket

    def _connect(self) -> Any:
        if self._client is None:
            boto3 = _boto3()
            options = self.spec.options
            endpoint = str(options.get("endpoint_url") or "").strip()
            try:
                from botocore.config import Config

                # botocore's own defaults are 60s with retries on top, so an
                # unreachable endpoint would sit for minutes. One retry, because
                # this is a user waiting on a page rather than a batch job.
                timeout = int(settings.CONNECTOR_TIMEOUT)
                self._client = boto3.client(
                    "s3",
                    config=Config(
                        connect_timeout=timeout,
                        read_timeout=timeout,
                        retries={"max_attempts": 1},
                    ),
                    # Empty means "the AWS default chain" -- environment, profile,
                    # instance role. A user on EC2 or with `aws configure` already
                    # done should not have to paste a key Wizard would then store.
                    endpoint_url=endpoint or None,
                    region_name=str(options.get("region") or "").strip() or None,
                    aws_access_key_id=str(options.get("access_key_id") or "").strip() or None,
                    aws_secret_access_key=self._secret or None,
                )
            except Exception as exc:
                raise ConnectorError("Could not open the connection.", detail=str(exc)) from exc
        return self._client

    # ------------------------------------------------------------------ #
    def test(self) -> None:
        client = self._connect()
        try:
            client.head_bucket(Bucket=self._bucket())
        except Exception as exc:
            raise ConnectorError("Could not reach the bucket.", detail=str(exc)) from exc

    def discover(self) -> ConnectionSchema:
        client = self._connect()
        bucket = self._bucket()
        prefix = str(self.spec.options.get("prefix") or "").strip()
        try:
            response = client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=LIST_LIMIT)
        except Exception as exc:
            raise ConnectorError("Could not list the bucket.", detail=str(exc)) from exc

        targets: list[TargetInfo] = []
        for entry in response.get("Contents") or []:
            key = str(entry.get("Key") or "")
            if not key or not key.lower().endswith(READABLE_SUFFIXES):
                continue
            targets.append(TargetInfo(name=key, namespace=bucket))
        return ConnectionSchema(targets=targets)

    def sample(self, target: str, limit: int = DEFAULT_SAMPLE_ROWS) -> pd.DataFrame:
        # Read whole, then bounded. An object store has no server-side row
        # limit -- the smallest unit it will return is the object -- so unlike the
        # relational connector there is nothing to push down, and pretending
        # otherwise would only hide where the cost actually is.
        frame = self._read_object(target)
        return frame.head(int(limit))

    def fetch(self, query: str) -> pd.DataFrame:
        """Reads one object whole. ``query`` is its key."""
        return self._read_object(query)

    def write(self, target: str, df: pd.DataFrame) -> None:
        refuse_write(self.spec)
        client = self._connect()
        buffer = io.BytesIO()
        if target.lower().endswith(".parquet"):
            df.to_parquet(buffer, index=False)
        else:
            buffer.write(df.to_csv(index=False).encode("utf-8"))
        try:
            client.put_object(Bucket=self._bucket(), Key=target, Body=buffer.getvalue())
        except Exception as exc:
            raise ConnectorError(f"Could not write to '{target}'.", detail=str(exc)) from exc

    def close(self) -> None:
        self._client = None

    # ------------------------------------------------------------------ #
    def _read_object(self, key: str) -> pd.DataFrame:
        client = self._connect()
        try:
            response = client.get_object(Bucket=self._bucket(), Key=key)
            payload = response["Body"].read()
        except Exception as exc:
            raise ConnectorError(f"Could not read '{key}'.", detail=str(exc)) from exc

        buffer = io.BytesIO(payload)
        lowered = key.lower()
        try:
            if lowered.endswith(".parquet"):
                return pd.read_parquet(buffer)
            if lowered.endswith(".feather"):
                return pd.read_feather(buffer)
            if lowered.endswith((".jsonl", ".ndjson")):
                return pd.read_json(buffer, lines=True)
            if lowered.endswith(".json"):
                return pd.read_json(buffer)
            return pd.read_csv(buffer, sep="\t" if lowered.endswith(".tsv") else ",")
        except Exception as exc:
            raise ConnectorError(f"Could not parse '{key}'.", detail=str(exc)) from exc


register(
    ConnectorKind(
        kind="objectstore",
        label="S3-compatible storage",
        factory=ObjectStoreConnector,
        module="boto3",
        distribution="boto3",
        fields=("bucket", "prefix", "region", "endpoint_url", "access_key_id"),
        requires_secret=False,
        description=(
            "Amazon S3, MinIO, Cloudflare R2 and other S3-compatible stores. "
            "CSV, TSV, JSON, Parquet and Feather objects are readable as tables."
        ),
    )
)


__all__ = ["ObjectStoreConnector"]
