type LiveActivityVisibility = {
  hasRunningTranscriptTool: boolean
  isStreaming: boolean
  liveMessageCount: number
  liveToolActivityCount: number
}

export function shouldShowLiveActivity({
  hasRunningTranscriptTool,
  isStreaming,
  liveMessageCount,
  liveToolActivityCount,
}: LiveActivityVisibility) {
  if (liveMessageCount > 0 || liveToolActivityCount > 0) {
    return true
  }
  return isStreaming && !hasRunningTranscriptTool
}
