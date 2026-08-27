import argparse
import logging
from datetime import datetime
import pytz

from e3vvid.video_processor import VideoProcessor
from upload_mp4_to_youtube import (
    check_youtube_upload_available,
)

logging.basicConfig(level=logging.DEBUG)

taipei = pytz.timezone("Asia/Taipei")


def parse_args():

    parser = argparse.ArgumentParser(
        description='Automatically combine multiple continuous time videos into one'
    )
    parser.add_argument(
        'src_video_dir',
        type=str,
        help='source video directory',
    )
    parser.add_argument(
        'dst_video_dir',
        type=str,
        help='destination video directory',
    )
    parser.add_argument(
        "times",
        help="input start time and end time scope that you want to combine, only 2 input",
        nargs="+",
        metavar="Times",
        default=[
            "2022-08-05T00:00:00",
            "2022-08-05T01:00:00",
        ],
    )
    parser.add_argument(
        "--upload-to-youtube",
        action="store_true",
        help="upload the combined video to youtube",
        default=False,
    )

    args = parser.parse_args()

    if len(args.times) != 2:
        raise ValueError("out of range")

    start_time, end_time = args.times
    format = "%Y-%m-%dT%H:%M:%S"  # 2022-08-05T01:00:00

    start_time = datetime.strptime(
        start_time, format
    ).astimezone(taipei)
    end_time = datetime.strptime(
        end_time, format
    ).astimezone(taipei)

    if start_time >= end_time:
        raise ValueError(
            "end_time is greater than start_time"
        )

    args.times = (start_time, end_time)

    return args


def main():
    args = parse_args()

    if args.upload_to_youtube:
        check_youtube_upload_available()

    vid_processor = VideoProcessor(
        src_video_dir=args.src_video_dir,
        dst_video_dir=args.dst_video_dir,
        start_time=args.times[0],
        end_time=args.times[1],
    )

    video_names = vid_processor.concat()
    print(f"合併後影片: {video_names}")

    if args.upload_to_youtube:
        vid_processor.upload_to_youtube(video_names)


if __name__ == '__main__':
    main()
