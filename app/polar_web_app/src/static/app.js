const form = document.getElementById("ask-form");
const questionEl = document.getElementById("question");
const conversationEl = document.getElementById("conversation");
const submitBtn = document.getElementById("submit");
const commandMenuEl = document.getElementById("command-menu");

let availableCommands = {};

// Pull configurable bits (title, the slash-command list) from the backend.
// Auth is handled entirely server-side via the session cookie — this page
// does no auth checks. Sign out is a plain form POST to /auth/logout (see
// index.html).
fetch("/config")
  .then((r) => r.json())
  .then((c) => {
    if (c.title) {
      document.getElementById("title").textContent = c.title;
      document.title = c.title;
    }
    if (c.commands) availableCommands = c.commands;
  })
  .catch(() => {});

// Deterministic, no-LLM-call welcome shown before the athlete types anything —
// what context is already stored (or a prompt to start giving it). Never part
// of the model conversation or persisted history, purely a UI greeting.
fetch("/greeting")
  .then((r) => r.json())
  .then((g) => {
    if (g.text) appendGreeting(g.text);
  })
  .catch(() => {});

// Slash-command discoverability: as soon as the input starts with "/", show
// matching commands (name + description, from /config's commands dict —
// the same commands.COMMANDS dict /help reads from, not duplicated here)
// below the textarea. Click-to-fill, no keyboard nav — plenty for a
// single-user app.
questionEl.addEventListener("input", () => {
  const value = questionEl.value;
  if (!value.startsWith("/")) {
    hideCommandMenu();
    return;
  }
  const matches = Object.entries(availableCommands).filter(([name]) => name.startsWith(value));
  if (matches.length === 0) {
    hideCommandMenu();
    return;
  }
  renderCommandMenu(matches);
});

function hideCommandMenu() {
  commandMenuEl.hidden = true;
  commandMenuEl.textContent = "";
}

function renderCommandMenu(matches) {
  commandMenuEl.textContent = "";
  for (const [name, description] of matches) {
    const item = document.createElement("div");
    item.className = "command-item";

    const nameEl = document.createElement("span");
    nameEl.className = "name";
    nameEl.textContent = name;

    const descEl = document.createElement("span");
    descEl.className = "desc";
    descEl.textContent = description;

    item.appendChild(nameEl);
    item.appendChild(descEl);
    item.addEventListener("click", () => {
      questionEl.value = name + " ";
      hideCommandMenu();
      questionEl.focus();
    });
    commandMenuEl.appendChild(item);
  }
  commandMenuEl.hidden = false;
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = questionEl.value.trim();
  if (!question) return;

  submitBtn.disabled = true;
  // Clear the input so the next question starts from an empty box.
  questionEl.value = "";
  hideCommandMenu();

  // Append this turn to the conversation history and stream into its answer.
  const { answerEl, textNode, spinner } = appendTurn(question);

  try {
    // The session cookie is sent automatically (same-origin request).
    const resp = await fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    if (resp.status === 401) {
      // Session missing or expired — the backend is the source of truth, so
      // send the user back to sign in again.
      window.location.assign("/login");
      return;
    }
    if (resp.status === 429) throw new Error("Rate limit reached — please slow down and try again shortly.");
    if (!resp.ok) throw new Error("Request failed: " + resp.status);

    await streamSSE(resp, (event) => handleEvent(event, answerEl, textNode, spinner));
  } catch (err) {
    if (spinner.isConnected) spinner.remove();
    const e = document.createElement("div");
    e.className = "error";
    e.textContent = "Error: " + err.message;
    answerEl.appendChild(e);
  } finally {
    submitBtn.disabled = false;
    questionEl.focus();
  }
});

// Create the DOM for one Q&A turn and append it to the conversation log.
// Returns the answer container, the text node that streamed text goes into,
// and a "thinking" spinner shown until the first SSE frame arrives.
function appendTurn(question) {
  const turn = document.createElement("div");
  turn.className = "turn";

  const q = document.createElement("div");
  q.className = "question";
  q.textContent = question;

  const answerEl = document.createElement("div");
  answerEl.className = "answer";
  const textNode = document.createElement("span");
  const spinner = document.createElement("div");
  spinner.className = "spinner";
  spinner.appendChild(document.createElement("span"));
  spinner.appendChild(document.createElement("span"));
  spinner.appendChild(document.createElement("span"));
  answerEl.appendChild(spinner);

  turn.appendChild(q);
  turn.appendChild(answerEl);
  conversationEl.appendChild(turn);
  turn.scrollIntoView({ behavior: "smooth", block: "start" });

  return { answerEl, textNode, spinner };
}

// Same .turn > .answer structure appendTurn uses, but with no preceding
// .question div — there's no user message yet when the greeting appears.
function appendGreeting(text) {
  const turn = document.createElement("div");
  turn.className = "turn";

  const answerEl = document.createElement("div");
  answerEl.className = "answer";
  answerEl.textContent = text;

  turn.appendChild(answerEl);
  conversationEl.appendChild(turn);
}

function handleEvent(event, answerEl, textNode, spinner) {
  if (spinner.isConnected) spinner.remove();
  switch (event.type) {
    case "tool": {
      const pill = document.createElement("div");
      pill.className = "tool";
      pill.textContent = "🔧 " + event.name + "(" + JSON.stringify(event.input) + ")";
      answerEl.appendChild(pill);
      if (!textNode.isConnected) answerEl.appendChild(textNode);
      break;
    }
    case "text":
      if (!textNode.isConnected) answerEl.appendChild(textNode);
      textNode.textContent += event.text;
      break;
    case "error": {
      const e = document.createElement("div");
      e.className = "error";
      e.textContent = "Error: " + event.message;
      answerEl.appendChild(e);
      break;
    }
    case "done":
      break;
  }
}
