// Reads a fetch Response body as a stream of Server-Sent Event frames
// (separated by "\n\n"), calling onEvent(parsedJSON) for each "data: ..."
// line. Handles frames split across chunk boundaries via a persistent
// buffer -- the actual non-trivial part of parsing SSE over a raw fetch
// stream (no EventSource here, since both /ask and /plan/ask need POST with
// a request body, which EventSource can't send). Shared by app.js and
// plan.js so there's one implementation of this, not two that could
// silently drift apart.
async function streamSSE(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sep;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const line = frame.replace(/^data: /, "");
      if (!line) continue;
      onEvent(JSON.parse(line));
    }
  }
}
