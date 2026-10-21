from concurrent.futures import ThreadPoolExecutor, as_completed
from dateutil.relativedelta import relativedelta
from datetime import timedelta
from dataclasses import dataclass
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from datetime import datetime, tzinfo
from threading import Event
import pytz
import sys
from subprocess import Popen, PIPE


@dataclass(frozen=True)
class AudioInfo:
    codec: str
    profile: str | None
    sample_rate: int
    channels: int

    @property
    def is_supported(self) -> bool:
        return self.codec == "aac" and self.profile in (None, "LC")

    def compatible(self, other: "AudioInfo") -> bool:
        return (
            self.is_supported
            and other.is_supported
            and self.sample_rate == other.sample_rate
            and self.channels == other.channels
        )


@dataclass
class GroupPlan:
    index: int
    lines: list[str]
    output_name: str
    prefix_lines: list[str]
    rest_lines: list[str]
    audio: AudioInfo | None
    use_fast_path: bool
    prefix_ok: bool = True
    prefix_out: str = ""


_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_AUDIO_RE = re.compile(
    r"Audio:\s*([A-Za-z0-9_]+)(?:\s*\(([^)]+)\))?(?:\s*\([^)]*\))?,"
    r"\s*(\d+)\s*Hz,\s*([^,]+)"
)


def _parse_ffmpeg_info(stderr: str) -> tuple[float | None, AudioInfo | None]:
    duration = None
    match = _DURATION_RE.search(stderr)
    if match is not None:
        hours, minutes, seconds = match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    match = _AUDIO_RE.search(stderr)
    if match is None:
        return duration, None

    codec = match.group(1).lower()
    profile = match.group(2).upper() if match.group(2) else None
    sample_rate = int(match.group(3))
    channels_text = match.group(4).strip().lower()
    channels = {"mono": 1, "stereo": 2}.get(channels_text)
    if channels is None:
        channels_match = re.match(r"(\d+)\s+channels", channels_text)
        if channels_match is not None:
            channels = int(channels_match.group(1))
    if channels is None:
        return duration, None

    return duration, AudioInfo(codec, profile, sample_rate, channels)


class VideoProcessor:
    def __init__(
        self,
        src_video_dir: str,
        dst_video_dir: str,
        start_time: datetime,
        end_time: datetime,
        timezone: tzinfo = pytz.timezone("Asia/Taipei"),
        merge_all: bool = False,
        mute_seconds: int = 0,
        ffmpeg_bin: str = "ffmpeg",
    ):
        self._src_video_dir = src_video_dir
        self._dst_video_dir = dst_video_dir
        self._start_time = start_time
        self._end_time = end_time
        self._timezone = timezone
        self._merge_all = merge_all
        self._mute_seconds = mute_seconds
        self._ffmpeg_bin = ffmpeg_bin

    def convert_filename_to_datetime(
        self, filename, format="%Y%m%d%H%M%S"
    ) -> datetime:
        vid = Path(filename)
        date_string = vid.stem.split("_")[0]
        naive = datetime.strptime(date_string, format)
        localize = getattr(self._timezone, "localize", None)
        if localize is not None:
            return localize(naive)
        return naive.replace(tzinfo=self._timezone)

    def get_videos(self, dir: str, suffix='.TS') -> list:
        """找出指定資料夾下 特定後綴的影片檔

        Args:
            dir (str): 要找尋影片檔的資料夾
            suffix (str, optional): 要找尋的影片檔後綴. Defaults to '.TS'.

        Returns:
            _type_: _description_
        """
        dir = Path(dir)
        # return list(sorted(dir.glob(f'*{suffix}')))
        return list(
            sorted(
                [
                    dir_.resolve().as_posix()
                    for dir_ in dir.iterdir()
                    if dir_.name[0] != '.'
                ]
            )
        )

    def find_continous_video(
        self, interval: timedelta = relativedelta(minutes=1)
    ):
        raw_videos = self.get_videos(self._src_video_dir)
        if len(raw_videos) == 0:
            raise ValueError("No videos")

        in_range = [
            vid
            for vid in raw_videos
            if self._start_time
            <= self.convert_filename_to_datetime(vid)
            < self._end_time
        ]
        if len(in_range) == 0:
            raise ValueError("No videos in time range")

        if self._merge_all:
            return [[f"file '{vid}'\n" for vid in in_range]]

        last_time = self.convert_filename_to_datetime(
            in_range[0], format="%Y%m%d%H%M%S"
        )
        tmp_list = []
        video_list = []
        for vid in in_range:
            file_date = self.convert_filename_to_datetime(
                vid, format="%Y%m%d%H%M%S"
            )
            this_time = last_time + interval
            if this_time != file_date:
                if len(tmp_list) != 0:
                    video_list.append(tmp_list.copy())
                    tmp_list.clear()
            tmp_list.append(f"file '{vid}'\n")
            last_time = file_date
        if len(tmp_list):
            video_list.append(tmp_list.copy())
        return video_list

    def _probe_media(
        self, path: str
    ) -> tuple[float | None, AudioInfo | None]:
        proc = Popen(
            [self._ffmpeg_bin, "-hide_banner", "-i", path],
            stdout=PIPE,
            stderr=PIPE,
            text=True,
        )
        _, stderr = proc.communicate()
        return _parse_ffmpeg_info(stderr)

    @staticmethod
    def _line_to_path(line: str) -> str:
        text = line.strip()
        if text.startswith("file '") and text.endswith("'"):
            return text[6:-1]
        return text

    def _plan_group(
        self,
        index: int,
        lines: list[str],
        cancel_event: Event | None = None,
    ) -> GroupPlan | None:
        if not lines:
            return None
        paths = [self._line_to_path(line) for line in lines]
        dat = self.convert_filename_to_datetime(paths[0])
        output_name = f"{dat.strftime('%Y_%m_%dT%H:%M:%S')}_muted.mp4"
        threshold = self._mute_seconds + 0.5
        total = 0.0
        audio = None
        prefix_count = 0

        for path in paths:
            if cancel_event is not None and cancel_event.is_set():
                return None
            duration, info = self._probe_media(path)
            if duration is None or info is None:
                return GroupPlan(
                    index, lines, output_name,
                    lines[:1], lines[1:], None, False,
                )
            if audio is None:
                audio = info
                if not audio.is_supported:
                    return GroupPlan(
                        index, lines, output_name,
                        lines[:1], lines[1:], audio, False,
                    )
            total += duration
            prefix_count += 1
            if total >= threshold:
                break

        prefix_count = max(1, prefix_count)
        prefix_lines = lines[:prefix_count]
        rest_lines = lines[prefix_count:]
        if rest_lines:
            for rest_path in paths[prefix_count:]:
                _, rest_info = self._probe_media(rest_path)
                if (
                    audio is None
                    or rest_info is None
                    or not audio.compatible(rest_info)
                ):
                    return GroupPlan(
                        index, lines, output_name,
                        prefix_lines, rest_lines, audio, False,
                    )
        return GroupPlan(
            index, lines, output_name,
            prefix_lines, rest_lines, audio, True,
        )

    def _build_concat_cmd(self, videolist: str, video_name: str) -> list:
        cmd = [
            self._ffmpeg_bin, "-y", "-f", "concat", "-safe", "0",
            "-i", videolist,
        ]
        if self._mute_seconds > 0:
            cmd += [
                "-c:v", "copy",
                "-af", f"volume=0.0:enable='lt(t,{self._mute_seconds})'",
                "-c:a", "aac",
            ]
        else:
            cmd += ["-c", "copy"]
        cmd.append(str(Path(self._dst_video_dir) / video_name))
        return cmd

    def _build_prefix_cmd(
        self, videolist: str, out_path: str, audio: AudioInfo
    ) -> list[str]:
        return [
            self._ffmpeg_bin, "-y", "-f", "concat", "-safe", "0",
            "-i", videolist,
            "-c:v", "copy",
            "-af", f"volume=0.0:enable='lt(t,{self._mute_seconds})'",
            "-c:a", "aac",
            "-ar", str(audio.sample_rate),
            "-ac", str(audio.channels),
            "-profile:a", "aac_low",
            out_path,
        ]

    def _build_final_concat_cmd(
        self, videolist: str, out_path: str
    ) -> list[str]:
        return [
            self._ffmpeg_bin, "-y", "-f", "concat", "-safe", "0",
            "-i", videolist, "-c", "copy",
            "-bsf:a", "aac_adtstoasc", out_path,
        ]

    def _run_ffmpeg(
        self,
        cmd: list[str],
        cancel_event: Event | None = None,
    ) -> tuple[int, str, str]:
        import time as _time

        if cancel_event is not None and cancel_event.is_set():
            return -9, "", "cancelled"

        logging.info(cmd)
        proc = Popen(cmd, stdout=PIPE, stderr=PIPE, text=True)

        if cancel_event is not None:
            while proc.poll() is None:
                if cancel_event.is_set():
                    proc.kill()
                    break
                _time.sleep(0.1)

        stdout, stderr = proc.communicate()
        return proc.returncode, stdout, stderr

    def _concat_copy(
        self,
        video_list: list,
        dst: Path,
        cancel_event: Event | None,
    ) -> list:
        video_names = []
        with tempfile.TemporaryDirectory() as tmpdir:
            for i, v in enumerate(video_list):
                if cancel_event is not None and cancel_event.is_set():
                    return []
                videolist = Path(tmpdir) / f"videolist{i}.txt"
                with open(videolist, "w", encoding="utf-8") as f:
                    f.writelines(v)

                dat = self.convert_filename_to_datetime(
                    self._line_to_path(v[0])
                )
                base_name = dat.strftime("%Y_%m_%dT%H:%M:%S")
                suffix = "_muted" if self._mute_seconds > 0 else ""
                video_name = f"{base_name}{suffix}.mp4"

                cmd = self._build_concat_cmd(videolist.as_posix(), video_name)
                rc, out, err = self._run_ffmpeg(cmd, cancel_event)
                if cancel_event is not None and cancel_event.is_set():
                    return []
                if rc != 0:
                    print("處理失敗:", err)
                    return []
                print("成功:", out)
                video_names.append(video_name)
        return video_names

    def _concat_muted(
        self,
        video_list: list,
        dst: Path,
        cancel_event: Event | None,
    ) -> list:
        plans = []
        for i, lines in enumerate(video_list):
            if cancel_event is not None and cancel_event.is_set():
                return []
            plan = self._plan_group(i, lines, cancel_event)
            if plan is None:
                return []
            plans.append(plan)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fast = []
            for plan in plans:
                if not plan.use_fast_path:
                    continue
                if plan.audio is None:
                    plan.use_fast_path = False
                    continue
                if plan.rest_lines:
                    plan.prefix_out = str(tmp / f"prefix{plan.index}.ts")
                else:
                    plan.prefix_out = str(dst / plan.output_name)
                prefix_list = tmp / f"prefix{plan.index}.txt"
                with open(prefix_list, "w", encoding="utf-8") as f:
                    f.writelines(plan.prefix_lines)
                cmd = self._build_prefix_cmd(
                    prefix_list.as_posix(),
                    plan.prefix_out,
                    plan.audio,
                )
                fast.append((plan, cmd))

            if fast:
                workers = max(1, min(4, os.cpu_count() or 1))
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    futures = {
                        executor.submit(
                            self._run_ffmpeg, cmd, cancel_event
                        ): plan
                        for plan, cmd in fast
                    }
                    for future in as_completed(futures):
                        plan = futures[future]
                        try:
                            rc, _, err = future.result()
                        except Exception as exc:
                            rc, err = -1, str(exc)
                        if (
                            cancel_event is not None
                            and cancel_event.is_set()
                        ):
                            return []
                        if rc != 0:
                            logging.error(
                                "prefix failed for %s: %s",
                                plan.output_name,
                                err,
                            )
                            plan.prefix_ok = False

            if cancel_event is not None and cancel_event.is_set():
                return []

            names = []
            for plan in plans:
                if cancel_event is not None and cancel_event.is_set():
                    return []
                if plan.use_fast_path and plan.prefix_ok:
                    if not plan.rest_lines:
                        names.append(plan.output_name)
                        continue
                    final_list = tmp / f"final{plan.index}.txt"
                    with open(final_list, "w", encoding="utf-8") as f:
                        f.write(f"file '{plan.prefix_out}'\n")
                        f.writelines(plan.rest_lines)
                    cmd = self._build_final_concat_cmd(
                        final_list.as_posix(),
                        str(dst / plan.output_name),
                    )
                    rc, _, err = self._run_ffmpeg(cmd, cancel_event)
                    if cancel_event is not None and cancel_event.is_set():
                        return []
                    if rc == 0:
                        names.append(plan.output_name)
                        continue
                    logging.error(
                        "final concat failed for %s: %s",
                        plan.output_name,
                        err,
                    )

                full_list = tmp / f"videolist{plan.index}.txt"
                with open(full_list, "w", encoding="utf-8") as f:
                    f.writelines(plan.lines)
                cmd = self._build_concat_cmd(
                    full_list.as_posix(),
                    plan.output_name,
                )
                rc, _, err = self._run_ffmpeg(cmd, cancel_event)
                if cancel_event is not None and cancel_event.is_set():
                    return []
                if rc != 0:
                    print("處理失敗:", err)
                    return []
                names.append(plan.output_name)
            return names

    def concat(self, cancel_event: Event | None = None) -> list:
        video_list = self.find_continous_video()
        dst = Path(self._dst_video_dir)
        dst.mkdir(parents=True, exist_ok=True)
        if self._mute_seconds > 0:
            return self._concat_muted(video_list, dst, cancel_event)
        return self._concat_copy(video_list, dst, cancel_event)

    def upload_to_youtube(self, video_names: list):
        results = []
        logging.info(
            f"start upload to youtube: {video_names}"
        )
        for video_name in video_names:
            video_path = (
                Path(self._dst_video_dir) / video_name
            )
            logging.info(
                f"uploading {video_path} to youtube"
            )

            cmd = [
                sys.executable,
                str(
                    Path(__file__).resolve().parent.parent
                    / "upload_mp4_to_youtube.py"
                ),
                video_path.as_posix(),
            ]

            proc = Popen(
                cmd,
                stdout=PIPE,
                stderr=PIPE,
                text=True,
            )
            stdout, stderr = proc.communicate()

            if stdout:
                logging.info(stdout.strip())

            result_line = next(
                (
                    line
                    for line in stdout.splitlines()
                    if line.startswith("RESULT_JSON=")
                ),
                None,
            )
            if result_line is not None:
                try:
                    results.append(
                        json.loads(
                            result_line.split("=", 1)[1]
                        )
                    )
                except json.JSONDecodeError:
                    logging.error(
                        "invalid upload result: %s",
                        result_line,
                    )

            if stderr:
                logging.error(stderr.strip())

            if proc.returncode != 0:
                logging.error(
                    "upload command failed: %s",
                    video_path.as_posix(),
                )

        logging.info(
            "youtube upload results: %s",
            json.dumps(
                results,
                ensure_ascii=False,
            ),
        )
        return results
