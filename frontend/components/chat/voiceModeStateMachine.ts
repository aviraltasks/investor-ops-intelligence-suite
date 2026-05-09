export type VoiceModeState =
  | "off"
  | "starting"
  | "speaking_welcome"
  | "listening"
  | "listening_paused"
  | "processing"
  | "speaking_reply"
  | "error_fallback";

export type VoiceModeEvent =
  | "ENABLE_CLICKED"
  | "WELCOME_SPEECH_STARTED"
  | "WELCOME_SPEECH_ENDED"
  | "USER_SPEECH_CAPTURED"
  | "ASSISTANT_REPLY_STARTED"
  | "ASSISTANT_REPLY_ENDED"
  | "MIC_STOPPED"
  | "LISTENING_STARTED"
  | "STOP_CLICKED"
  | "VOICE_FAILURE"
  | "PAGE_CLOSED";

export type VoiceTransition = {
  from: VoiceModeState;
  event: VoiceModeEvent;
  to: VoiceModeState;
  note: string;
};

export const VOICE_TRANSITIONS: VoiceTransition[] = [
  // Entry and boot.
  { from: "off", event: "ENABLE_CLICKED", to: "starting", note: "User explicitly enables hands-free voice mode." },
  { from: "starting", event: "WELCOME_SPEECH_STARTED", to: "speaking_welcome", note: "Welcome TTS starts speaking." },
  { from: "starting", event: "VOICE_FAILURE", to: "error_fallback", note: "Failed to initialize speech or mic." },

  // Welcome -> listen.
  { from: "speaking_welcome", event: "WELCOME_SPEECH_ENDED", to: "listening", note: "Auto-engage mic after welcome ends." },
  { from: "speaking_welcome", event: "VOICE_FAILURE", to: "error_fallback", note: "Welcome TTS failed mid-playback." },

  // Listening -> processing / paused.
  { from: "listening", event: "USER_SPEECH_CAPTURED", to: "processing", note: "Mic captured user utterance; send request." },
  { from: "listening", event: "MIC_STOPPED", to: "listening_paused", note: "User stopped mic while hands-free session stays on." },
  { from: "listening", event: "VOICE_FAILURE", to: "error_fallback", note: "Speech recognition failed." },

  { from: "listening_paused", event: "LISTENING_STARTED", to: "listening", note: "Mic started again (manual or auto)." },
  { from: "listening_paused", event: "VOICE_FAILURE", to: "error_fallback", note: "Recognizer error while idle." },

  // Processing -> assistant speech.
  { from: "processing", event: "ASSISTANT_REPLY_STARTED", to: "speaking_reply", note: "Assistant reply TTS starts." },
  { from: "processing", event: "VOICE_FAILURE", to: "error_fallback", note: "Reply synthesis failed." },

  // Continuous loop.
  { from: "speaking_reply", event: "ASSISTANT_REPLY_ENDED", to: "listening", note: "Auto-engage mic for next user utterance." },
  { from: "speaking_reply", event: "VOICE_FAILURE", to: "error_fallback", note: "Reply speech interrupted by runtime failure." },

  // Universal stop/close.
  { from: "starting", event: "STOP_CLICKED", to: "off", note: "User disabled voice mode." },
  { from: "speaking_welcome", event: "STOP_CLICKED", to: "off", note: "User disabled voice mode." },
  { from: "listening", event: "STOP_CLICKED", to: "off", note: "User disabled voice mode." },
  { from: "listening_paused", event: "STOP_CLICKED", to: "off", note: "User disabled voice mode." },
  { from: "processing", event: "STOP_CLICKED", to: "off", note: "User disabled voice mode." },
  { from: "speaking_reply", event: "STOP_CLICKED", to: "off", note: "User disabled voice mode." },
  { from: "error_fallback", event: "STOP_CLICKED", to: "off", note: "Reset fallback state back to normal chat." },

  { from: "starting", event: "PAGE_CLOSED", to: "off", note: "Session ended by navigation/close." },
  { from: "speaking_welcome", event: "PAGE_CLOSED", to: "off", note: "Session ended by navigation/close." },
  { from: "listening", event: "PAGE_CLOSED", to: "off", note: "Session ended by navigation/close." },
  { from: "listening_paused", event: "PAGE_CLOSED", to: "off", note: "Session ended by navigation/close." },
  { from: "processing", event: "PAGE_CLOSED", to: "off", note: "Session ended by navigation/close." },
  { from: "speaking_reply", event: "PAGE_CLOSED", to: "off", note: "Session ended by navigation/close." },
  { from: "error_fallback", event: "PAGE_CLOSED", to: "off", note: "Session ended by navigation/close." },

  // Recovery path: user can re-enable after fallback.
  { from: "error_fallback", event: "ENABLE_CLICKED", to: "starting", note: "User retries voice mode." },
];

export function nextVoiceModeState(current: VoiceModeState, event: VoiceModeEvent): VoiceModeState {
  const match = VOICE_TRANSITIONS.find((t) => t.from === current && t.event === event);
  return match ? match.to : current;
}
