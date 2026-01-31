"""
HLS proxy endpoints for video streaming.
"""

import asyncio
import re
import httpx
from fastapi import APIRouter, Response
from fastapi.responses import StreamingResponse

from config import stream_cache, HTTP_STREAMING_TIMEOUT, HTTP_MAX_KEEPALIVE, HTTP_MAX_CONNECTIONS
from streaming import get_stream_urls

router = APIRouter()


@router.get("/mcp/proxy/playlist.m3u8")
async def proxy_playlist(channel: int = 548, cdn: int = 0):
    """Proxy the HLS playlist file"""
    # Get the original URL from cache
    if channel not in stream_cache:
        await get_stream_urls(channel)

    original_url = stream_cache[channel][cdn]

    # Fetch the playlist
    async with httpx.AsyncClient() as client:
        response = await client.get(original_url)
        playlist_content = response.text

    # Rewrite URLs in the playlist to go through our proxy
    # Extract base URL for chunks
    base_url = original_url.rsplit('/', 1)[0]

    # Replace relative URLs with proxied URLs
    def replace_url(match):
        chunk_file = match.group(1)
        if chunk_file.startswith('http'):
            # Already absolute URL
            encoded_url = str(chunk_file).replace('/', '%2F').replace(':', '%3A').replace('?', '%3F').replace('=', '%3D').replace('&', '%26')
        else:
            # Relative URL - make it absolute then encode
            absolute_url = f"{base_url}/{chunk_file}"
            encoded_url = str(absolute_url).replace('/', '%2F').replace(':', '%3A').replace('?', '%3F').replace('=', '%3D').replace('&', '%26')
        return f'/mcp/proxy/chunk?url={encoded_url}'

    # Replace chunk URLs in the playlist
    playlist_content = re.sub(r'^((?:https?://)?[^\s#]+\.(?:ts|m3u8))$', replace_url, playlist_content, flags=re.MULTILINE)

    # Add CODECS attribute to EXT-X-STREAM-INF if missing
    # H.264 Main Profile Level 4.2 (avc1.4d002a) + AAC-LC (mp4a.40.2)
    def add_codecs(match):
        line = match.group(0)
        if 'CODECS=' not in line:
            # Add CODECS before the end of the line
            return line + ',CODECS="avc1.4d002a,mp4a.40.2"'
        return line

    playlist_content = re.sub(r'#EXT-X-STREAM-INF:[^\n]+', add_codecs, playlist_content)

    return Response(
        content=playlist_content,
        media_type='application/vnd.apple.mpegurl',
        headers={
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, OPTIONS',
            'Access-Control-Allow-Headers': '*',
            'Cache-Control': 'no-cache, no-store, must-revalidate',  # Prevent caching
            'Pragma': 'no-cache',
            'Expires': '0',
        }
    )


@router.get("/mcp/proxy/chunk")
async def proxy_chunk(url: str, transcode: bool = False):
    """Proxy individual video chunks and sub-playlists"""
    if not url:
        return Response('Missing URL', status_code=400)

    # If it's another playlist, rewrite URLs in it too
    if '.m3u8' in url:
        async with httpx.AsyncClient(
            timeout=HTTP_STREAMING_TIMEOUT,
            limits=httpx.Limits(max_keepalive_connections=HTTP_MAX_KEEPALIVE, max_connections=HTTP_MAX_CONNECTIONS)
        ) as client:
            response = await client.get(url)
            content = response.text
            base_url = url.rsplit('/', 1)[0]

            def replace_url(match):
                chunk_file = match.group(1)
                if chunk_file.startswith('http'):
                    encoded_url = str(chunk_file).replace('/', '%2F').replace(':', '%3A').replace('?', '%3F').replace('=', '%3D').replace('&', '%26')
                else:
                    absolute_url = f"{base_url}/{chunk_file}"
                    encoded_url = str(absolute_url).replace('/', '%2F').replace(':', '%3A').replace('?', '%3F').replace('=', '%3D').replace('&', '%26')
                return f'/mcp/proxy/chunk?url={encoded_url}'

            content = re.sub(r'^((?:https?://)?[^\s#]+\.(?:ts|m3u8))$', replace_url, content, flags=re.MULTILINE)

            # Remove #EXT-X-ENDLIST if present (indicates VOD, not live)
            content = re.sub(r'#EXT-X-ENDLIST\s*\n?', '', content)

            # Ensure it's marked as a live/event stream if not already
            if '#EXT-X-PLAYLIST-TYPE' not in content:
                # Don't add PLAYLIST-TYPE for live streams - let it remain dynamic
                pass

            return Response(
                content=content,
                media_type='application/vnd.apple.mpegurl',
                headers={
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Methods': 'GET, OPTIONS',
                    'Access-Control-Allow-Headers': '*',
                    'Cache-Control': 'no-cache, no-store, must-revalidate',  # Prevent caching
                    'Pragma': 'no-cache',
                    'Expires': '0',
                }
            )

    # For video chunks, transcode audio to AAC-LC if needed
    if transcode and url.endswith('.ts'):
        async def transcode_stream():
            try:
                async with httpx.AsyncClient(timeout=HTTP_STREAMING_TIMEOUT) as client:
                    async with client.stream('GET', url) as response:
                        # Start ffmpeg process with GPU acceleration
                        process = await asyncio.create_subprocess_exec(
                            'ffmpeg',
                            '-hwaccel', 'cuda',           # Use CUDA hardware acceleration
                            '-hwaccel_output_format', 'cuda',  # Keep decoded frames on GPU
                            '-i', 'pipe:0',
                            '-c:v', 'copy',               # Copy video (no re-encoding needed)
                            '-c:a', 'aac',                # Transcode audio to AAC
                            '-b:a', '128k',
                            '-ar', '48000',
                            '-f', 'mpegts',
                            'pipe:1',
                            stdin=asyncio.subprocess.PIPE,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.DEVNULL
                        )

                        # Background task to feed input to ffmpeg
                        async def feed_stdin():
                            try:
                                # Larger chunks = fewer system calls = faster
                                async for chunk in response.aiter_bytes(chunk_size=65536):
                                    try:
                                        process.stdin.write(chunk)
                                        await process.stdin.drain()
                                    except (BrokenPipeError, ConnectionResetError):
                                        break
                                process.stdin.close()
                            except Exception as e:
                                print(f"Error feeding ffmpeg: {e}")
                                try:
                                    process.kill()
                                except:
                                    pass

                        feeder = asyncio.create_task(feed_stdin())

                        # Read output from ffmpeg with larger chunks
                        try:
                            while True:
                                chunk = await process.stdout.read(65536)
                                if not chunk:
                                    break
                                yield chunk
                        finally:
                            # Cleanup
                            if process.returncode is None:
                                try:
                                    process.terminate()
                                    try:
                                        await asyncio.wait_for(process.wait(), timeout=1.0)
                                    except asyncio.TimeoutError:
                                        process.kill()
                                except OSError:
                                    pass

                            if not feeder.done():
                                feeder.cancel()
                                try:
                                    await feeder
                                except asyncio.CancelledError:
                                    pass

                            await process.wait()

            except Exception as e:
                print(f"Streaming error: {e}")
                pass

        return StreamingResponse(
            transcode_stream(),
            media_type='video/MP2T',
            headers={
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, OPTIONS',
                'Access-Control-Allow-Headers': '*',
            }
        )

    # For non-.ts chunks or if transcoding fails/is disabled, stream them through unchanged
    async def generate():
        async with httpx.AsyncClient(
            timeout=HTTP_STREAMING_TIMEOUT,
            limits=httpx.Limits(max_keepalive_connections=HTTP_MAX_KEEPALIVE, max_connections=HTTP_MAX_CONNECTIONS)
        ) as client:
            async with client.stream('GET', url) as response:
                # Larger chunks for better throughput
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    yield chunk

    return StreamingResponse(
        generate(),
        media_type='video/MP2T',
        headers={
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, OPTIONS',
            'Access-Control-Allow-Headers': '*',
        }
    )

