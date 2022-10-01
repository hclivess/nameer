ffprobe -print_format json -show_format -show_entries stream=bit_rate,codec_type,codec_name,height,channels,tags,index:stream_tags=language %1
pause