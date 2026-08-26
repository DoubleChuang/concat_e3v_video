from dateutil.relativedelta import relativedelta
from datetime import timedelta
import json
import logging
from pathlib import Path
from datetime import datetime, tzinfo
from threading import Event
import pytz
import shlex
import subprocess
from subprocess import Popen, PIPE


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
        d = datetime.strptime(
            date_string, format
        ).astimezone(self._timezone)

        return d

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
                    dir_.as_posix()
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

    def concat(self, cancel_event: Event | None = None) -> list:
        import time as _time
        video_list = self.find_continous_video()
        try:
            dst = Path(self._dst_video_dir)
            dst.mkdir(parents=True, exist_ok=True)

            procs = []
            video_names = []
            for i, v in enumerate(video_list):
                if cancel_event is not None and cancel_event.is_set():
                    break
                videolist = Path(f"videolist{i}.txt")
                with open(videolist, "w") as f:
                    f.writelines(v)

                dat = self.convert_filename_to_datetime(v[0])
                base_name = dat.strftime("%Y_%m_%dT%H:%M:%S")
                suffix = "_muted" if self._mute_seconds > 0 else ""
                video_name = f"{base_name}{suffix}.mp4"

                cmd = self._build_concat_cmd(
                    videolist.as_posix(), video_name
                )
                logging.info(cmd)
                proc = Popen(cmd, stdout=PIPE, stderr=PIPE, text=True)
                procs.append(proc)
                video_names.append(video_name)

                if cancel_event is not None:
                    while proc.poll() is None:
                        if cancel_event.is_set():
                            proc.kill()
                            break
                        _time.sleep(0.1)
                else:
                    proc.communicate()

            for p in procs:
                if p.returncode != 0:
                    print("處理失敗:", p.stderr)
                    return []
                else:
                    print("成功:", p.stdout)

            return video_names
        finally:
            for i, v in enumerate(video_list):
                Path(f"videolist{i}.txt").unlink(missing_ok=True)

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

            cmd = shlex.split(
                f'python3 upload_mp4_to_youtube.py {video_path.as_posix()} '
            )

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
