import asyncio
import subprocess
from datetime import datetime
from pathlib import Path

from streamget import DouyinLiveStream


async def download_live_stream(url: str, output_dir: str = "downloads", quality: str = "OD", duration: int = None, cookies: str = None):
    """
    下载抖音直播流到本地文件
    
    Args:
        url: 抖音直播间URL
        output_dir: 输出目录
        quality: 画质选项 (OD/UHD/HD/SD/LD)
        duration: 录制时长(秒), None表示持续录制直到手动停止
        cookies: 可选的cookies, 如果遇到反爬可以添加
    """
    # 创建输出目录
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # 初始化抖音直播流对象
    douyin_stream = DouyinLiveStream(cookies=cookies)
    
    try:
        print(f"[{quality}] 正在获取直播间信息: {url}")
        
        # 先尝试使用 web 方法，失败则尝试 app 方法
        data = None
        try:
            data = await douyin_stream.fetch_web_stream_data(url)
        except Exception as e1:
            print(f"[{quality}] Web方法失败，尝试App方法: {e1}")
            try:
                data = await douyin_stream.fetch_app_stream_data(url)
            except Exception as e2:
                raise Exception(f"Web和App方法都失败: Web={str(e1)[:50]}, App={str(e2)[:50]}")
        
        # 检查是否在直播 (status: 2=直播中, 4=未开播)
        status = data.get('status', 4)
        if status != 2:
            print(f"[{quality}] ❌ 主播未开播 (status={status})")
            return
        
        print(f"[{quality}] ✅ 主播: {data.get('anchor_name')}")
        print(f"[{quality}] 📺 标题: {data.get('title')}")
        
        # 获取流地址
        stream_data = await douyin_stream.fetch_stream_url(data, quality)
        
        # 优先使用 FLV，稳定性更好
        stream_url = stream_data.flv_url or stream_data.m3u8_url
        
        if not stream_url:
            print(f"[{quality}] ❌ 未获取到流地址")
            return
        
        print(f"[{quality}] 🔗 流地址: {stream_url[:80]}...")
        
        # 生成输出文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        anchor_name = data.get('anchor_name', 'unknown').replace('/', '_')
        
        # 根据流类型选择扩展名
        if stream_url.endswith('.m3u8') or 'm3u8' in stream_url:
            ext = 'mp4'  # HLS流保存为mp4
        else:
            ext = 'flv'  # FLV流保存为flv
        
        # 文件名包含画质信息，避免并发录制时冲突
        output_file = Path(output_dir) / f"{anchor_name}_{quality}_{timestamp}.{ext}"
        
        print(f"[{quality}] 💾 开始录制，保存到: {output_file.name}")
        if duration:
            print(f"[{quality}] ⏱️  录制时长: {duration}秒 ({duration//60}分{duration%60}秒)")
        else:
            print(f"[{quality}] ⏱️  持续录制，按 Ctrl+C 停止...")
        
        # 使用 FFmpeg 下载
        await download_with_ffmpeg(stream_url, str(output_file), duration, quality)
        
    except KeyboardInterrupt:
        print(f"\n[{quality}] ⏹️ 用户停止录制")
    except Exception as e:
        print(f"[{quality}] ❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()


async def download_with_ffmpeg(stream_url: str, output_file: str, duration: int = None, quality: str = ""):
    """
    使用 FFmpeg 下载直播流（真正的异步执行）
    
    Args:
        stream_url: 流地址
        output_file: 输出文件路径
        duration: 录制时长(秒), None表示持续录制
        quality: 画质标识，用于日志输出
    """
    # FFmpeg 命令
    cmd = [
        'ffmpeg',
        '-i', stream_url,           # 输入流
        '-c', 'copy',                # 直接复制流，不重新编码（速度快）
        '-bsf:a', 'aac_adtstoasc',  # AAC 音频转换
    ]
    
    # 添加时长限制
    if duration:
        cmd.extend(['-t', str(duration)])  # 限制录制时长
    
    cmd.extend([
        '-f', 'mp4' if output_file.endswith('.mp4') else 'flv',
        '-y',                        # 覆盖已存在的文件
        output_file
    ])
    
    # 使用异步方式执行 FFmpeg（真正的并发）
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    # 异步等待进程结束
    stdout, stderr = await process.communicate()
    
    if process.returncode == 0:
        print(f"[{quality}] ✅ 录制完成: {Path(output_file).name}")
    else:
        error_msg = stderr.decode('utf-8', errors='ignore')[:200]
        print(f"[{quality}] ❌ FFmpeg 错误: {error_msg}")


async def download_with_requests(stream_url: str, output_file: str):
    """
    使用 requests 直接下载流（适用于小文件或短时录制）
    
    Args:
        stream_url: 流地址
        output_file: 输出文件路径
    """
    import requests
    
    print(f"📥 开始下载到: {output_file}")
    
    try:
        response = requests.get(stream_url, stream=True, timeout=10)
        response.raise_for_status()
        
        total_size = 0
        with open(output_file, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    total_size += len(chunk)
                    # 每 10MB 输出一次进度
                    if total_size % (10 * 1024 * 1024) < 8192:
                        print(f"📊 已下载: {total_size / (1024*1024):.2f} MB")
        
        print(f"✅ 下载完成: {output_file} ({total_size / (1024*1024):.2f} MB)")
        
    except Exception as e:
        print(f"❌ 下载错误: {e}")


async def main():
    # 抖音直播间 URL
    url = "https://live.douyin.com/901113773259"  # 可以换成其他直播间
    
    # 下载配置
    output_dir = "downloads"     # 保存目录
    duration = 600              # 录制时长(秒), None=持续录制, 用于调试可设置如 30/60/300
    
    # 可选：添加 cookies 避免反爬（如果遇到错误可以从浏览器复制）
    cookies = None  # 例如: "ttwid=xxx; __ac_nonce=xxx"
    
    # 方式1: 单个画质录制（推荐先测试单个）
    # quality = "OD"  # 画质: OD(原画)/UHD(超清)/HD(高清)/SD(标清)/LD(流畅)
    # await download_live_stream(url, output_dir, quality, duration, cookies)
    
    # 方式2: 多个画质并发录制（同时录制）
    quality_list = ["OD", "UHD", "HD", "SD", "LD"]  # 选择要录制的画质
    print(f"\n🚀 开始并发录制 {len(quality_list)} 个画质: {', '.join(quality_list)}\n")
    
    tasks = [
        download_live_stream(url, output_dir, q, duration, cookies)
        for q in quality_list
    ]
    
    # 并发执行所有任务
    await asyncio.gather(*tasks)
    
    print(f"\n✅ 所有画质录制完成！")


if __name__ == "__main__":
    asyncio.run(main())
