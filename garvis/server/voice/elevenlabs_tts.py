"""
Eleven Labs Real-time Text-to-Speech

Uses the ElevenLabs SDK's convert_realtime() which supports streaming text input.
This enables low-latency audio - audio starts playing while Claude is still generating text.
"""

import asyncio
import queue
import threading
from typing import Callable, Awaitable, Optional, Iterator

from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings
from config import ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL_ID


class ElevenLabsTTS:
    """
    Real-time text-to-speech using ElevenLabs' streaming input API.
    
    Key feature: Text is streamed in as it arrives from Claude, and audio
    is streamed out as it's generated. This gives the lowest possible latency.
    """
    
    def __init__(
        self,
        on_audio: Callable[[bytes], Awaitable[None]],
        voice_id: str = ELEVENLABS_VOICE_ID,
        model_id: str = ELEVENLABS_MODEL_ID
    ):
        if not ELEVENLABS_API_KEY:
            raise ValueError("ELEVENLABS_API_KEY is not set")
        
        self.on_audio = on_audio
        self.voice_id = voice_id
        self.model_id = model_id
        
        self.client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
        
        self._text_queue: queue.Queue[Optional[str]] = queue.Queue()
        self._audio_queue: queue.Queue[Optional[bytes]] = queue.Queue()
        self._synthesis_thread: Optional[threading.Thread] = None
        self._audio_task: Optional[asyncio.Task] = None
        self._stop_event = threading.Event()
        self._is_speaking = False
    
    def _text_iterator(self) -> Iterator[str]:
        """
        Generator that yields text chunks from the queue.
        Used by convert_realtime() to stream text input.
        """
        while True:
            try:
                text = self._text_queue.get(timeout=0.1)
                if text is None:  # Signal to stop
                    break
                yield text
            except queue.Empty:
                if self._stop_event.is_set():
                    break
                continue
    
    def _synthesis_worker(self):
        """
        Worker thread that runs convert_realtime and puts audio chunks in queue.
        """
        try:
            print("🔊 Starting real-time TTS synthesis...")
            
            audio_iter = self.client.text_to_speech.convert_realtime(
                voice_id=self.voice_id,
                text=self._text_iterator(),
                model_id=self.model_id,
                output_format="mp3_44100_128",
                voice_settings=VoiceSettings(
                    stability=0.5,
                    similarity_boost=0.75,
                    style=0.0,
                    use_speaker_boost=True
                )
            )
            
            # Stream audio chunks to the queue as they're generated
            for chunk in audio_iter:
                if self._stop_event.is_set():
                    break
                self._audio_queue.put(chunk)
            
            print("✅ TTS synthesis complete")
            
        except Exception as e:
            print(f"❌ TTS synthesis error: {e}")
        finally:
            # Signal end of audio
            self._audio_queue.put(None)
    
    async def _audio_sender(self):
        """
        Async task that sends audio chunks from the queue to the client.
        """
        try:
            while True:
                # Check for audio in queue (non-blocking with small timeout)
                try:
                    chunk = await asyncio.get_event_loop().run_in_executor(
                        None, 
                        lambda: self._audio_queue.get(timeout=0.05)
                    )
                    
                    if chunk is None:  # End of audio
                        break
                    
                    await self.on_audio(chunk)
                    
                except queue.Empty:
                    if self._stop_event.is_set():
                        break
                    await asyncio.sleep(0.01)
                    continue
                    
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"❌ Audio sending error: {e}")
    
    async def add_text(self, text: str):
        """
        Add text to be converted to speech.
        Text is queued and processed in real-time.
        """
        if not self._is_speaking:
            # Start streaming on first text
            self._is_speaking = True
            self._stop_event.clear()
            
            # Start synthesis thread
            self._synthesis_thread = threading.Thread(target=self._synthesis_worker)
            self._synthesis_thread.start()
            
            # Start audio sender task
            self._audio_task = asyncio.create_task(self._audio_sender())
        
        self._text_queue.put(text)
    
    async def flush(self):
        """Signal end of text and wait for audio to finish"""
        if not self._is_speaking:
            return
            
        # Signal end of text input
        self._text_queue.put(None)
        
        # Wait for synthesis thread to complete
        if self._synthesis_thread:
            await asyncio.get_event_loop().run_in_executor(
                None, self._synthesis_thread.join
            )
            self._synthesis_thread = None
        
        # Wait for audio sender to complete
        if self._audio_task:
            try:
                await self._audio_task
            except asyncio.CancelledError:
                pass
            self._audio_task = None
        
        self._is_speaking = False
        print("✅ Real-time TTS streaming complete")
    
    async def stop(self):
        """Stop current TTS playback immediately"""
        self._stop_event.set()
        
        # Clear queues
        while not self._text_queue.empty():
            try:
                self._text_queue.get_nowait()
            except queue.Empty:
                break
        
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break
        
        # Signal end
        self._text_queue.put(None)
        
        # Wait for threads/tasks to stop
        if self._synthesis_thread:
            await asyncio.get_event_loop().run_in_executor(
                None, self._synthesis_thread.join, 1.0
            )
            self._synthesis_thread = None
        
        if self._audio_task:
            self._audio_task.cancel()
            try:
                await self._audio_task
            except asyncio.CancelledError:
                pass
            self._audio_task = None
        
        self._is_speaking = False
        self._stop_event.clear()
