#!/usr/bin/env bash
# Check tundra worker logs for recent compilation activity

ssh winter@192.168.1.119 -p 2222 "cd ClippyFront && cat flask-dev.log" | grep -E "compile_video_task_v2|_build_timeline|intro_id|outro_id|transition" | tail -50
