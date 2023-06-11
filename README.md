# concat e3v video

將`e3v`行車記錄器的連續ts片段，合併成一個mp4檔案

## How to use

```
usage: main.py [-h] src_video_dir dst_video_dir Times [Times ...]

Automatically combine multiple continuous time videos into one

positional arguments:
  src_video_dir  source video directory
  dst_video_dir  destination video directory
  Times          input start time and end time scope that you want to combine, only 2 input

options:
  -h, --help     show this help message and exit
```

example
```
python3 main.py /Volumes/Untitled/DCIM/Front Front 2023-06-09T16:00:00 2023-06-10T00:00:00
```
