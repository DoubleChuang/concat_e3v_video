from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import Callable

from e3vvid.video_processor import VideoProcessor
from upload_mp4_to_youtube import upload_video


def _noop(msg: str) -> None:
    pass


@dataclass
class PipelineConfig:
    src_dir: str
    dst_dir: str
    start_time: datetime
    end_time: datetime
    merge_all: bool = False
    mute_seconds: int = 0
    ffmpeg_bin: str = "ffmpeg"
    upload_enabled: bool = False
    upload_title: str | None = None
    upload_description: str | None = None
    upload_privacy: str = "private"
    upload_tags: str | None = None
    upload_playlist: str | None = None
    client_secrets: str | None = None
    credentials_file: str | None = None
    cancel_event: Event | None = None
    auth_callback: Callable[[], bool] | None = None
    log: Callable[[str], None] = field(default=_noop)


def _check_auth(cfg: PipelineConfig) -> bool:
    if cfg.auth_callback is None:
        return False
    return cfg.auth_callback()


def run_pipeline(cfg: PipelineConfig) -> dict:
    if cfg.upload_enabled and not _check_auth(cfg):
        return {
            "status": "aborted",
            "reason": "youtube-auth-failed",
            "video_names": [],
            "upload_results": [],
        }

    cfg.log(f"開始合併: {cfg.src_dir} -> {cfg.dst_dir}")
    processor = VideoProcessor(
        src_video_dir=cfg.src_dir,
        dst_video_dir=cfg.dst_dir,
        start_time=cfg.start_time,
        end_time=cfg.end_time,
        merge_all=cfg.merge_all,
        mute_seconds=cfg.mute_seconds,
        ffmpeg_bin=cfg.ffmpeg_bin,
    )

    video_names = processor.concat(cancel_event=cfg.cancel_event)
    if not video_names:
        return {
            "status": "failed",
            "reason": "concat-failed",
            "video_names": [],
            "upload_results": [],
        }
    cfg.log(f"合併後影片: {video_names}")

    upload_results = []
    if cfg.upload_enabled:
        if not _check_auth(cfg):
            return {
                "status": "aborted",
                "reason": "youtube-auth-failed",
                "video_names": video_names,
                "upload_results": [],
            }
        for name in video_names:
            if cfg.cancel_event is not None and cfg.cancel_event.is_set():
                break
            path = Path(cfg.dst_dir) / name
            cfg.log(f"上傳 {path} 到 YouTube...")
            result = upload_video(
                str(path),
                title=cfg.upload_title,
                description=cfg.upload_description,
                tags=cfg.upload_tags,
                privacy=cfg.upload_privacy,
                playlist=cfg.upload_playlist,
                client_secrets=cfg.client_secrets,
                credentials_file=cfg.credentials_file,
            )
            upload_results.append(result)
            if result.get("exit_code") == 0:
                cfg.log(f"上傳成功: {result.get('video_id')}")
            else:
                cfg.log(f"上傳失敗: {result.get('error')}")

    return {
        "status": "done",
        "video_names": video_names,
        "upload_results": upload_results,
        "reason": None,
    }