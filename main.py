from pathlib import Path
import argparse
import logging
from datetime import datetime
from dateutil.relativedelta import relativedelta

logging.basicConfig(level=logging.DEBUG)

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

    return args

def get_videos(dir, suffix='.TS', interval: relativedelta = relativedelta(minute=1)):
    dir = Path(dir)
    logging.info(dir)
    
    return list(sorted(dir.glob(f'**/*{suffix}')))
    

def main():
    args = parse_args()
    src_video_dir = args.src_video_dir
    dst_video_dir = args.dst_video_dir
    start_time, end_time = args.times

    format = "%Y-%m-%dT%H:%M:%S" #2022-08-05T01:00:00
    start_time = datetime.strptime(start_time, format)
    end_time = datetime.strptime(end_time, format)

    video_list = []
    # video_list_idx = 0
    videos = get_videos(src_video_dir)
    last_time = datetime.utcnow() + relativedelta(hours=8)
    tmp_list = []

    for i, vid in enumerate(videos):
        vid = Path(vid)
        stem = vid.stem
        stem = stem.split("_")[0]
        format = "%Y%m%d%H%M%S"
        d = datetime.strptime(stem, format)

        if not (start_time <= d < end_time):
            continue

        # logging.info(f'last_time: {last_time}')
        this_time = last_time + relativedelta(minutes=1)
        
        # logging.info(f'this_time: {this_time}')
        if i!=0 and this_time != d:
            video_list.append(tmp_list.copy())
            tmp_list.clear()

        tmp_list.append(f"file '{vid}'\n")
        logging.info(f'tmp_list: {len(tmp_list)}')
        last_time = d
    
    if len(tmp_list):
        video_list.append(tmp_list.copy())
        
    for i, v in enumerate(video_list):
        with open(f"videolist{i}.txt", "w") as f:
            logging.info(v)
            f.writelines(v)           


if __name__ == '__main__':
    main()