from dateutil.relativedelta import relativedelta
from datetime import timedelta
import logging
from pathlib import Path
from datetime import datetime, tzinfo
import pytz
import shlex
from subprocess import Popen, PIPE

class VideoProcessor():
    def __init__(self, 
        src_video_dir:str, 
        dst_video_dir:str,
        start_time:datetime,
        end_time:datetime,
        timezone:tzinfo = pytz.timezone("Asia/Taipei"),
    ):
        self._src_video_dir = src_video_dir 
        self._dst_video_dir = dst_video_dir
        self._start_time = start_time
        self._end_time = end_time
        self._timezone = timezone
    
    def convert_filename_to_datetime(self, filename, format="%Y%m%d%H%M%S") -> datetime:
        vid = Path(filename)        
        date_string = vid.stem.split("_")[0]
        d = datetime.strptime(date_string, format).astimezone(self._timezone)

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
        return list(sorted([dir_.as_posix() for dir_ in dir.iterdir() if dir_.name[0]!='.']))
    
    def find_continous_video(self, interval: timedelta=relativedelta(minutes=1)):
        """找出連續的影片

        因為每段都是固定時間一個檔，透過設定的`interval`找出連續的影片
        example: 假設機器設定每一分鐘錄一個檔，則interval設定 1 分鐘的 timedelta

        Args:
            interval (relativedelta, optional): 
            找出上一個影片跟下個影片的間隔是否差距一分鐘.
            Defaults to relativedelta(minutes=1).
        """
        raw_videos = self.get_videos(self._src_video_dir)
        if len(raw_videos) == 0:
            raise ValueError("No videos")

        # init
        last_time = self.convert_filename_to_datetime(raw_videos[0], format = "%Y%m%d%H%M%S")
        tmp_list = []
        video_list = []

        for vid in raw_videos:
            # 解析檔名取出時間            
            file_date = self.convert_filename_to_datetime(vid, format = "%Y%m%d%H%M%S")

            # 比對時間有在範圍內
            if not (self._start_time <= file_date < self._end_time):
                continue

            this_time = last_time + interval
            if this_time != file_date:
                if len(tmp_list) != 0:
                    video_list.append(tmp_list.copy())
                    tmp_list.clear()
            
            # ffmpeg concat file format
            tmp_list.append(f"file '{vid}'\n")            
            last_time = file_date
        
        if len(tmp_list):
            video_list.append(tmp_list.copy())
        
        return video_list

    def concat(self):
        video_list = self.find_continous_video()
    
        dst = Path(self._dst_video_dir)
        dst.mkdir(parents=True, exist_ok=True)
        
        procs = []
        for i, v in enumerate(video_list):
            videolist = Path(f"videolist{i}.txt")
            with open(videolist, "w") as f:            
                f.writelines(v)
            
            dat = self.convert_filename_to_datetime(v[0])
            
            cmd = shlex.split(
                f'ffmpeg -y -f concat -safe 0 -i {videolist} -c copy {self._dst_video_dir}/{dat.strftime("%Y_%m_%dT%H:%M:%S")}.mp4'
            )
            logging.info(cmd)
            
            procs.append(Popen(cmd, stdout=PIPE, stderr=PIPE))        
        
        for p in procs:
            stdout, stderr = p.communicate()
            # logging.info(stdout)
            # logging.info(stderr)
        
        for i, v in enumerate(video_list):
            videolist = Path(f"videolist{i}.txt")
            videolist.unlink()
