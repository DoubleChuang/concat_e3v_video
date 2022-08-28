from pathlib import Path
import argparse
import logging
from datetime import datetime
import pytz
from dateutil.relativedelta import relativedelta
from e3vvid.video_processor import VideoProcessor
from subprocess import Popen, PIPE
import shlex


logging.basicConfig(level=logging.DEBUG)

taipei = pytz.timezone("Asia/Taipei")

def parse_args():
    
    parser = argparse.ArgumentParser(description='Automatically combine multiple continuous time videos into one')
    parser.add_argument('src_video_dir', type=str, help='source video directory')
    parser.add_argument('dst_video_dir', type=str, help='destination video directory')
    parser.add_argument(
        "times",
        help="input start time and end time scope that you want to combine, only 2 input",
        nargs="+",
        metavar="Times",
        default=["2022-08-05T00:00:00", "2022-08-05T01:00:00"],
    )

    args = parser.parse_args()
    
    if len(args.times) != 2:
        raise ValueError("out of range")
    
    start_time, end_time = args.times
    format = "%Y-%m-%dT%H:%M:%S" #2022-08-05T01:00:00
    
    start_time = datetime.strptime(start_time, format).astimezone(taipei)
    end_time = datetime.strptime(end_time, format).astimezone(taipei)
    
    args.times = (start_time, end_time)

    return args

def get_videos(dir, suffix='.TS', interval: relativedelta = relativedelta(minute=1)):
    dir = Path(dir)
    logging.info(dir)
    
    return list(sorted(dir.glob(f'**/*{suffix}')))
    

def main():

    args = parse_args()   

    vid_processor = VideoProcessor(
        src_video_dir=args.src_video_dir,
        dst_video_dir=args.dst_video_dir,
        start_time = args.times[0],
        end_time = args.times[1]
    )
    video_list = vid_processor.find_continous_video()
    
    for i, v in enumerate(video_list):
        videolist = Path(f"videolist{i}.txt") 
        with open(videolist, "w") as f:            
            f.writelines(v)
        
        command = shlex.split(f"ffmpeg -y -f concat -safe 0 -i {videolist} -c copy video{i}.mp4")        
        logging.info(command)
        process = Popen(command, stdout=PIPE, stderr=PIPE)
        stdout, stderr = process.communicate()        
        videolist.unlink()

if __name__ == '__main__':
    main()