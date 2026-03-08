import asyncio
from pathlib import Path
import json
import wave
from vosk import KaldiRecognizer,Model
import edge_tts

CURRENTFOLDER = Path(__file__).parent.resolve()


class Voice_GEN:
    def __init__(self, voice: str = "en-US-AriaNeural"):

        self.voicepath = CURRENTFOLDER / "outputs"
        self.modelpath=CURRENTFOLDER/"vosk-model-small-en-us-0.15"
        self.MODEL=Model(self.modelpath)
        self.voicepath.mkdir(exist_ok=True)  # create folder if missing
        self.voice = voice
        self.n = 0

    async def text_to_voice(self, text: str) -> str:

        full_path = self.voicepath / f"voice{self.n}.ogg"

        communicate = edge_tts.Communicate(text, self.voice)

        await communicate.save(str(full_path))

        self.n += 1  # increment counter

        return str(full_path)
    async def voice_to_text(self,audiopath:str)->str:
        waf=wave.open(audiopath,"rb")
        if waf.getnchannels()!=1 or waf.getsampwidth()!=2:
            print("Audio must be mono Wav PCM")
            exit()
        recognizer=KaldiRecognizer(self.MODEL,waf.getframerate())
        while True:
            data=waf.readframes(4000)
            if len(data)==0:
                break
            if recognizer.AcceptWaveform(data):
                result=json.loads(recognizer.Result())
                print(result)
        
        final_result=json.loads(recognizer.FinalResult())
        return final_result 
        
            
        
        
