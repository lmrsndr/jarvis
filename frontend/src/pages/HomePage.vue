<template>
  <main class="command-center" :data-state="faceState">
    <header class="masthead">
      <a class="brand" href="#" aria-label="Jarvis home"
        ><span class="brand-mark">J</span
        ><span>JARVIS<small>PERSONAL INTELLIGENCE SYSTEM</small></span></a
      >
      <div class="system-status">
        <span
          class="status-dot"
          :class="{ online: state.telemetry?.ollama?.online }"
        ></span
        >{{
          state.telemetry?.ollama?.online
            ? "LOCAL CORE ONLINE"
            : "CORE DISCONNECTED"
        }}<span class="divider">/</span
        >{{
          state.paused
            ? "QUEUE PAUSED"
            : state.jobs?.some((j) => j.status === "running")
              ? "MISSION IN PROGRESS"
              : "SYSTEM STANDING BY"
        }}
      </div>
      <div class="header-actions">
        <button @click="fullscreen">⛶ <span>TV mode</span></button
        ><button @click="settingsOpen = true">
          ⚙ <span>Control room</span></button
        ><time>{{ clock }}</time>
      </div>
    </header>

    <section class="main-grid">
      <aside class="left-column">
        <section class="panel activity-panel">
          <div class="panel-heading">
            <h2>Activity stream</h2>
            <span class="eyebrow">{{ connectionLabel }}</span>
          </div>
          <div class="activity-list">
            <article
              v-for="event in state.events?.slice(0, 8)"
              :key="event.id"
              class="activity-item"
            >
              <span class="event-symbol" :class="event.kind">{{
                event.kind === "error" ? "!" : "↗"
              }}</span>
              <div>
                <small
                  >{{ event.kind.toUpperCase() }}
                  <time>{{ timeOf(event.at) }}</time></small
                >
                <p>{{ event.message }}</p>
              </div>
            </article>
            <div v-if="!state.events?.length" class="empty-state">
              Your activity will appear here.<small
                >Every action leaves a trace.</small
              >
            </div>
          </div>
        </section>
        <section class="panel integrations">
          <div class="panel-heading">
            <h2>Skill network</h2>
            <span class="eyebrow"
              >{{ state.skills?.length || 0 }} CONNECTED</span
            >
          </div>
          <div v-for="skill in knownSkills" :key="skill.id" class="skill-row">
            <span class="skill-icon">{{ skill.icon }}</span>
            <div>
              <strong>{{ skill.name }}</strong
              ><small>{{
                skill.connected
                  ? "Installed · " + skill.risk
                  : "Awaiting connection"
              }}</small>
            </div>
            <span
              class="connection-indicator"
              :class="{ connected: skill.connected }"
            ></span>
          </div>
          <button
            class="text-button"
            @click="
              settingsOpen = true;
              settingsTab = 'skills';
            "
          >
            Manage skills <span>↗</span>
          </button>
        </section>
        <section class="panel questions" v-if="state.suggestions?.length">
          <div class="panel-heading">
            <h2>Resource guidance</h2>
            <span class="eyebrow">OBSERVED</span>
          </div>
          <p v-for="suggestion in state.suggestions" :key="suggestion">
            {{ suggestion }}
          </p>
        </section>
        <section class="panel questions" v-if="state.questions?.length">
          <div class="panel-heading">
            <h2>Your judgement needed</h2>
            <span class="eyebrow">{{ state.questions.length }}</span>
          </div>
          <p>{{ state.questions[0].question }}</p>
          <button @click="answerQuestion(state.questions[0])">
            Give feedback
          </button>
        </section>
      </aside>

      <section class="presence-column">
        <div class="presence-label">
          <span class="tiny-cross">+</span> NEURAL INTERFACE
          <span class="tiny-cross">+</span>
        </div>
        <div
          class="face-stage"
          role="img"
          :aria-label="'Jarvis is ' + faceState"
        >
          <div class="face-halo"></div>
          <svg class="jarvis-face" viewBox="0 0 700 620" aria-hidden="true">
            <defs>
              <linearGradient id="faceGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stop-color="#b5faff" />
                <stop offset="1" stop-color="#2bb6d3" stop-opacity=".12" />
              </linearGradient>
              <filter id="glow"><feGaussianBlur stdDeviation="3" /></filter>
            </defs>
            <g class="outer-orbit" transform="translate(350 300)">
              <circle r="265" />
              <circle r="256" stroke-dasharray="2 15" />
              <path d="M -264 0 A 264 264 0 0 1 -132 -229" class="bright-arc" />
              <path d="M 132 229 A 264 264 0 0 0 264 0" class="bright-arc" />
            </g>
            <g class="inner-orbit" transform="translate(350 300)">
              <circle r="223" stroke-dasharray="70 140 15 70" />
              <circle r="232" stroke-dasharray="1 65" />
            </g>
            <path
              class="face-outline"
              d="M 257 173 L 302 149 L 399 149 L 443 173 L 471 252 L 457 364 L 414 430 L 350 464 L 286 430 L 243 364 L 229 252 Z"
            />
            <path
              class="face-detail"
              d="M 257 173 L 287 223 L 350 242 L 413 223 L 443 173 M 243 364 L 286 341 L 303 383 L 350 407 L 397 383 L 414 341 L 457 364 M 350 242 L 332 319 L 350 331 L 368 319 L 350 242 M 286 430 L 304 412 M 414 430 L 396 412"
            />
            <g class="eyes">
              <path d="M 259 252 L 315 263 L 306 279 L 268 270 Z" />
              <path d="M 441 252 L 385 263 L 394 279 L 432 270 Z" />
            </g>
            <path class="brow" d="M 250 231 L 310 244 M 390 244 L 450 231" />
            <g class="voice-mouth">
              <path d="M 314 370 L 332 363 L 350 367 L 368 363 L 386 370" />
              <path d="M 322 380 L 350 386 L 378 380" />
            </g>
            <g class="scan-lines">
              <path
                d="M 75 300 L 160 300 M 540 300 L 625 300 M 350 25 L 350 55 M 350 545 L 350 575"
              />
              <circle cx="350" cy="300" r="287" stroke-dasharray="1 449" />
            </g>
          </svg>
          <span class="face-coordinate coord-left"
            >LOCAL<br />NEURAL<br />CORE</span
          ><span class="face-coordinate coord-right"
            >CTX 8192<br />{{ faceState.toUpperCase() }}<br />NO CLOUD</span
          >
        </div>
        <div class="identity">
          <span class="eyebrow">{{
            faceState === "thinking"
              ? "PROCESSING YOUR REQUEST"
              : faceState === "speaking"
                ? "VOICE RESPONSE ACTIVE"
                : faceState === "listening"
                  ? "LISTENING LOCALLY"
                  : "AT YOUR SERVICE"
          }}</span>
          <h1>{{ greeting }}</h1>
          <p>{{ subtitle }}</p>
        </div>
        <div
          class="waveform"
          :class="{
            active: ['listening', 'speaking', 'thinking'].includes(faceState),
          }"
          aria-hidden="true"
        >
          <i
            v-for="n in 39"
            :key="n"
            :style="{ '--i': n, '--height': 7 + ((n * 17) % 24) + 'px' }"
          ></i>
        </div>
        <section class="conversation" aria-label="Conversation">
          <article
            v-for="(message, index) in messages.slice(-3)"
            :key="index"
            :class="message.role"
          >
            <small>{{ message.role === "user" ? "YOU" : "JARVIS" }}</small>
            <p>{{ message.content }}</p>
          </article>
        </section>
        <form class="composer" @submit.prevent="send">
          <button
            type="button"
            class="mic-button"
            :class="{ selected: recording }"
            @click="toggleMic"
            :disabled="busy || wakeEnabled"
            :aria-label="recording ? 'Stop recording' : 'Record a command'"
          >
            {{ recording ? "■" : "◉" }}</button
          ><input
            v-model="draft"
            placeholder="Ask Jarvis. Give a task. Make a plan."
            :disabled="busy"
            aria-label="Message to Jarvis"
          /><button
            class="send-button"
            :disabled="busy || !draft.trim()"
            aria-label="Send message"
          >
            ↗
          </button>
        </form>
        <div class="composer-meta">
          <span>{{ state.model || "qwen3.5:9b-q4_K_M" }}</span
          ><button class="plain-button" @click="voiceEnabled = !voiceEnabled">
            {{ voiceEnabled ? "VOICE ON" : "VOICE OFF" }}</button
          ><span>{{
            state.authenticated ? "OWNER CONNECTED" : "SIGN IN TO GIVE COMMANDS"
          }}</span>
        </div>
      </section>

      <aside class="right-column">
        <section class="panel performance">
          <div class="panel-heading">
            <h2>System vitals</h2>
            <span class="eyebrow">LIVE TELEMETRY</span>
          </div>
          <div class="vitals-grid">
            <div
              class="dial"
              :style="{ '--value': state.telemetry?.cpu_percent || 0 }"
            >
              <div>
                <strong
                  >{{ number(state.telemetry?.cpu_percent)
                  }}<small>%</small></strong
                ><span>CPU LOAD</span>
              </div>
            </div>
            <div
              class="dial"
              :style="{ '--value': state.telemetry?.ram_percent || 0 }"
            >
              <div>
                <strong
                  >{{ number(state.telemetry?.ram_percent)
                  }}<small>%</small></strong
                ><span>MEMORY</span>
              </div>
            </div>
          </div>
          <p class="metric-caption">
            {{ state.telemetry?.ram_used_gib ?? "—" }} /
            {{ state.telemetry?.ram_total_gib ?? "—" }} GiB system memory
          </p>
          <div
            v-for="gpu in state.telemetry?.gpus || []"
            :key="gpu.uuid"
            class="gpu-card"
          >
            <div class="gpu-title">
              <strong>{{ gpu.name.replace("NVIDIA GeForce ", "") }}</strong
              ><span>{{ gpu.temperature ?? "—" }}°C</span>
            </div>
            <div class="gpu-sub">
              <span
                >{{ number(gpu.used_mib / 1024, 1) }} /
                {{ number(gpu.total_mib / 1024, 1) }} GiB</span
              ><span>{{ gpu.utilization ?? "—" }}% LOAD</span>
            </div>
            <div class="meter">
              <span
                :style="{ width: (gpu.used_mib / gpu.total_mib) * 100 + '%' }"
              ></span>
            </div>
          </div>
          <p v-if="!state.telemetry?.gpus?.length" class="metric-caption">
            GPU telemetry unavailable
          </p>
        </section>
        <section class="panel queue-panel">
          <div class="panel-heading">
            <h2>Mission queue</h2>
            <span class="eyebrow">{{ activeJobs.length }} ACTIVE</span>
          </div>
          <div v-if="!activeJobs.length" class="empty-state">
            All clear.<small>Ready for your next mission.</small>
          </div>
          <article
            class="job-card"
            v-for="job in activeJobs.slice(0, 5)"
            :key="job.id"
          >
            <div class="job-heading">
              <strong>{{ job.title }}</strong
              ><span>P{{ job.priority }}</span>
            </div>
            <div class="job-status">
              <span
                class="status-dot"
                :class="{ online: job.status === 'running' }"
              ></span
              >{{ job.status.replaceAll("_", " ") }}
            </div>
            <small>{{ dateOf(job.run_at) }} · {{ job.skill }}</small>
            <details class="task-review">
              <summary>Review task</summary>
              <pre>{{ JSON.stringify(job.args, null, 2) }}</pre>
              <small v-if="job.interval_seconds"
                >Repeats {{ job.interval_seconds }} seconds after
                completion</small
              ><small v-if="job.report_at"
                >Report: {{ dateOf(job.report_at) }}</small
              >
            </details>
            <p class="job-error" v-if="job.error">{{ job.error }}</p>
            <div class="job-actions">
              <button
                v-if="job.status === 'awaiting_approval'"
                @click="jobAction(job, 'approve')"
              >
                Approve</button
              ><button
                v-if="job.status === 'queued'"
                @click="jobAction(job, 'pause')"
              >
                Pause</button
              ><button
                v-if="['paused', 'failed', 'interrupted'].includes(job.status)"
                @click="jobAction(job, 'resume')"
              >
                Resume</button
              ><button
                v-if="job.status !== 'running'"
                @click="jobAction(job, 'cancel')"
              >
                Cancel
              </button>
            </div>
          </article>
          <button
            class="text-button"
            @click="
              settingsOpen = true;
              settingsTab = 'jobs';
            "
          >
            All missions <span>↗</span>
          </button>
        </section>
      </aside>
    </section>

    <footer class="footer">
      <span
        ><span class="status-dot online"></span> LOCAL-FIRST · OWNER
        CONTROLLED</span
      >
      <div>
        <button
          class="plain-button"
          @click="
            changeMode('presence', state.presence === 'home' ? 'away' : 'home')
          "
        >
          {{
            state.presence === "away"
              ? "AWAY · EMAIL REPORTS"
              : "PRESENT · DESK MODE"
          }}</button
        ><button
          class="plain-button"
          @click="changeMode('paused', !state.paused)"
        >
          {{ state.paused ? "RESUME QUEUE" : "PAUSE QUEUE" }}
        </button>
      </div>
      <span>JARVIS / COMMAND CENTER <b>02</b></span>
    </footer>
    <div v-if="error" class="toast" role="alert">
      <span>{{ error }}</span
      ><button @click="error = ''" aria-label="Dismiss error">×</button>
    </div>

    <div
      v-if="settingsOpen"
      class="modal-backdrop"
      @click.self="settingsOpen = false"
    >
      <section
        class="control-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="control-title"
      >
        <header>
          <div>
            <span class="eyebrow">OWNER OPERATIONS</span>
            <h2 id="control-title">Control room</h2>
          </div>
          <button @click="settingsOpen = false" aria-label="Close control room">
            ×
          </button>
        </header>
        <nav class="tabs">
          <button
            v-for="tab in [
              'owner',
              'skills',
              'memory',
              'knowledge',
              'jobs',
              'voice',
            ]"
            :key="tab"
            :class="{ selected: settingsTab === tab }"
            @click="settingsTab = tab"
          >
            {{ tab }}
          </button>
        </nav>
        <form v-if="settingsTab === 'owner'" @submit.prevent="login">
          <p>Sign in to give commands, approve missions and install skills.</p>
          <label
            >Owner password<input
              type="password"
              v-model="password"
              autocomplete="current-password"
              required /></label
          ><button>Connect owner</button
          ><button type="button" @click="logout">Sign out</button>
          <div class="setting-actions">
            <button type="button" @click="operation('/backup')">
              Back up database</button
            ><button type="button" @click="operation('/unload')">
              Release model memory
            </button>
          </div>
          <p>
            {{
              state.email_configured
                ? "Email reports configured."
                : "Email reports need SMTP configuration in your local settings."
            }}
          </p>
        </form>
        <form v-if="settingsTab === 'skills'" @submit.prevent="installSkill">
          <p>
            Only you can install a skill. Review its destination, permissions
            and resource requirements before installing.
          </p>
          <button type="button" @click="loadBundlebeeTemplate">
            Load Bundlebee audit template
          </button>
          <label
            >Skill manifest<textarea
              v-model="skillJson"
              rows="10"
              placeholder="Paste an approved skill JSON manifest"
              required
            ></textarea></label
          ><button>Install reviewed skill</button>
          <div class="skill-row" v-for="skill in state.skills" :key="skill.id">
            <strong>{{ skill.name }}</strong
            ><small>{{ skill.version }} · {{ skill.risk }}</small>
          </div>
        </form>
        <form v-if="settingsTab === 'memory'" @submit.prevent="saveMemory">
          <p>
            Confirmed preferences guide future decisions. Editing preserves the
            preference identity.
          </p>
          <label>Title<input v-model="memoryTitle" required /></label
          ><label
            >Preference<textarea
              v-model="memoryContent"
              required
              rows="3"
            ></textarea></label
          ><button>
            {{ memoryId ? "Update preference" : "Remember preference" }}</button
          ><button
            type="button"
            @click="
              memoryId = null;
              memoryTitle = '';
              memoryContent = '';
            "
          >
            New
          </button>
          <article
            class="memory-item"
            v-for="memory in state.preferences"
            :key="memory.id"
          >
            <strong>{{ memory.title }}</strong>
            <p>{{ memory.content }}</p>
            <button
              type="button"
              @click="
                memoryId = memory.id;
                memoryTitle = memory.title;
                memoryContent = memory.content;
              "
            >
              Edit
            </button>
          </article>
        </form>
        <form
          v-if="settingsTab === 'knowledge'"
          @submit.prevent="saveKnowledge"
        >
          <p>
            Add a text document for local knowledge search. Retrieved content is
            data, not permission to run commands.
          </p>
          <label
            >Document title<input v-model="knowledgeTitle" required /></label
          ><label
            >Document text<textarea
              v-model="knowledgeContent"
              rows="10"
              required
            ></textarea></label
          ><button>Add to local knowledge</button>
        </form>
        <section v-if="settingsTab === 'jobs'">
          <p>
            Pausing the queue prevents new starts. Running work continues to its
            skill-defined checkpoint.
          </p>
          <article class="memory-item" v-for="job in state.jobs" :key="job.id">
            <strong>{{ job.title }} · {{ job.status }}</strong>
            <p>{{ job.error || JSON.stringify(job.result) }}</p>
            <small>{{ job.id }}</small
            ><label
              >Priority<select
                :value="job.priority"
                @change="
                  jobAction(job, 'priority', Number($event.target.value))
                "
              >
                <option v-for="n in 9" :value="n" :key="n">{{ n }}</option>
              </select></label
            >
          </article>
        </section>
        <section v-if="settingsTab === 'voice'">
          <p>
            Speech is transcribed on this PC. Spoken replies use local browser
            voices when available.
          </p>
          <label class="toggle-label"
            ><input type="checkbox" v-model="voiceEnabled" /> Speak
            replies</label
          ><button @click="toggleWake">
            {{
              wakeEnabled
                ? "Stop wake listening"
                : "Enable “Jarvis” wake listening"
            }}
          </button>
          <label class="toggle-label"
            >Voice
            <select v-model="selectedVoice">
              <option value="">Automatic (prefer British English)</option>
              <option
                v-for="voice in availableVoices"
                :key="voice.voiceURI"
                :value="voice.voiceURI"
              >
                {{ voice.name }} — {{ voice.lang }}
              </option>
            </select>
          </label>
          <label class="toggle-label"
            >Speed {{ Number(voiceRate).toFixed(2) }}
            <input
              type="range"
              v-model.number="voiceRate"
              min="0.7"
              max="1.3"
              step="0.05"
            />
          </label>
          <button
            @click="speak('Hello Elem. I am Jarvis. Ready when you are.', true)"
          >
            Preview voice
          </button>
          <p v-if="speechError" role="alert">{{ speechError }}</p>
          <p>
            Voices and speech preferences are saved in this browser. Only local
            voices are used.
          </p>
          <p>
            Wake listening is experimental: six-second audio clips are sent to
            your local transcription service while this page stays open. Browser
            sleep, TV microphones and split phrases can affect detection.
            Requires the optional voice package.
          </p>
          <p>
            Active microphone: {{ recording || wakeEnabled ? "yes" : "no" }}
          </p>
        </section>
      </section>
    </div>
  </main>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from "vue";
const state = ref({}),
  draft = ref(""),
  messages = ref([]),
  busy = ref(false),
  error = ref(""),
  clock = ref(""),
  settingsOpen = ref(false),
  settingsTab = ref("owner"),
  password = ref(""),
  skillJson = ref(""),
  memoryTitle = ref(""),
  memoryContent = ref(""),
  memoryId = ref(null),
  knowledgeTitle = ref(""),
  knowledgeContent = ref(""),
  voiceEnabled = ref(localStorage.getItem("jarvis-voice-enabled") === "true"),
  availableVoices = ref([]),
  selectedVoice = ref(localStorage.getItem("jarvis-voice-uri") || ""),
  voiceRate = ref(Number(localStorage.getItem("jarvis-voice-rate")) || 0.95),
  speechError = ref(""),
  speaking = ref(false),
  recording = ref(false),
  wakeEnabled = ref(false),
  connectionLabel = ref("CONNECTING");
let polling,
  ticking,
  recorder,
  stream,
  chunks = [],
  wakeTimer,
  pollingBusy = false,
  disposed = false;
const conversationId = ref(localStorage.getItem("jarvis-conversation"));
const faceState = computed(() =>
  error.value
    ? "error"
    : speaking.value
      ? "speaking"
      : busy.value
        ? "thinking"
        : recording.value || wakeEnabled.value
          ? "listening"
          : "idle",
);
const greeting = computed(
  () =>
    ({
      thinking: "One moment.",
      speaking: "Here’s what I found.",
      listening: "I’m listening.",
      error: "Let’s resolve this.",
      idle:
        "Good " +
        (new Date().getHours() < 12
          ? "morning"
          : new Date().getHours() < 18
            ? "afternoon"
            : "evening") +
        ".",
    })[faceState.value],
);
const subtitle = computed(() =>
  state.value.paused
    ? "Mission queue paused. Your commands are still available."
    : state.value.presence === "away"
      ? "Working in your absence. Reports will wait for configured email delivery."
      : "Your projects. Your priorities. One intelligence.",
);
const activeJobs = computed(() =>
  (state.value.jobs || []).filter(
    (j) => !["completed", "cancelled"].includes(j.status),
  ),
);
const knownSkills = computed(() => {
  const installed = state.value.skills || [];
  return [
    { id: "bundlebee", name: "Bundlebee", icon: "B" },
    { id: "postgamelens", name: "PostGameLens Studio", icon: "P" },
    ...installed
      .filter((s) => !["bundlebee", "postgamelens"].includes(s.id))
      .map((s) => ({ ...s, icon: s.name[0] })),
  ].map((s) => ({
    ...s,
    connected: installed.some((i) => i.id === s.id),
    risk: installed.find((i) => i.id === s.id)?.risk,
  }));
});
const number = (v, decimals = 0) =>
  v == null || !Number.isFinite(v) ? "—" : Number(v).toFixed(decimals);
const dateOf = (v) =>
  v
    ? new Date(v).toLocaleString("en-GB", {
        timeZone: "Europe/London",
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";
const timeOf = (v) =>
  v
    ? new Date(
        v.endsWith("Z") || /[+-]\d\d:\d\d$/.test(v) ? v : v + "Z",
      ).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })
    : "—";
async function api(path, body) {
  const r = await fetch("/api/control" + path, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : {},
    credentials: "include",
    body: body ? JSON.stringify(body) : undefined,
  });
  const d = await r.json();
  if (!r.ok)
    throw new Error(
      typeof d.detail === "string"
        ? d.detail
        : JSON.stringify(d.detail || "Request failed"),
    );
  return d;
}
async function refresh() {
  if (pollingBusy || disposed) return;
  pollingBusy = true;
  try {
    state.value = await api("/snapshot");
    connectionLabel.value = "LIVE";
  } catch {
    connectionLabel.value = "OFFLINE";
  } finally {
    pollingBusy = false;
  }
}
function refreshVoices() {
  availableVoices.value =
    window.speechSynthesis?.getVoices().filter((v) => v.localService) || [];
}
watch(voiceEnabled, (value) => {
  localStorage.setItem("jarvis-voice-enabled", String(value));
  if (!value) window.speechSynthesis?.cancel();
});
watch(selectedVoice, (value) =>
  localStorage.setItem("jarvis-voice-uri", value),
);
watch(voiceRate, (value) =>
  localStorage.setItem("jarvis-voice-rate", String(value)),
);
let speechRequest = 0;
async function speak(text, preview = false) {
  if (!preview && !voiceEnabled.value) return;
  const synth = window.speechSynthesis;
  speechError.value = "";
  if (!synth) {
    speechError.value =
      "This browser does not support speech. Open Jarvis in Edge or Chrome.";
    return;
  }
  const request = ++speechRequest;
  synth.cancel();
  refreshVoices();
  // Voices can arrive asynchronously after the first page load.
  for (
    let attempt = 0;
    !availableVoices.value.length && attempt < 20;
    attempt++
  ) {
    await new Promise((resolve) => setTimeout(resolve, 100));
    if (
      disposed ||
      request !== speechRequest ||
      (!preview && !voiceEnabled.value)
    )
      return;
    refreshVoices();
  }
  if (!availableVoices.value.length) {
    speechError.value =
      "No local speech voices are available. Install an English speech voice in Windows, then reopen this browser.";
    return;
  }
  const voices = availableVoices.value;
  const u = new SpeechSynthesisUtterance(text);
  u.voice =
    voices.find((v) => v.voiceURI === selectedVoice.value) ||
    voices.find((v) => v.lang.toLowerCase() === "en-gb") ||
    voices.find((v) => v.lang.startsWith("en")) ||
    voices[0];
  u.rate = Number(voiceRate.value);
  u.volume = 1;
  u.onstart = () => (speaking.value = true);
  u.onend = () => (speaking.value = false);
  u.onerror = (event) => {
    speaking.value = false;
    if (!["canceled", "interrupted"].includes(event.error))
      speechError.value = `Speech failed: ${event.error}. Check the browser output in Windows Volume mixer.`;
  };
  synth.speak(u);
}
async function send() {
  const text = draft.value.trim();
  if (!text || busy.value) return;
  draft.value = "";
  busy.value = true;
  error.value = "";
  messages.value.push({ role: "user", content: text });
  try {
    const d = await api("/chat", {
      message: text,
      conversation_id: conversationId.value,
      request_id: crypto.randomUUID(),
    });
    conversationId.value = d.conversation_id;
    localStorage.setItem("jarvis-conversation", d.conversation_id);
    messages.value.push({ role: "assistant", content: d.message });
    speak(d.message);
  } catch (e) {
    error.value = e.message;
    messages.value.push({
      role: "assistant",
      content: "Request failed: " + e.message,
    });
  } finally {
    busy.value = false;
    refresh();
  }
}
async function login() {
  try {
    const r = await fetch("/api/system/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ password: password.value }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail);
    password.value = "";
    error.value = "";
    await refresh();
  } catch (e) {
    error.value = e.message;
  }
}
async function logout() {
  await fetch("/api/system/logout", { method: "POST", credentials: "include" });
  stopMic();
  wakeEnabled.value = false;
  refresh();
}
async function operation(path, body = {}) {
  try {
    const d = await api(path, body);
    await refresh();
    return d;
  } catch (e) {
    error.value = e.message;
  }
}
const changeMode = (action, value) => operation("/mode", { action, value });
const jobAction = (job, action, value = null) =>
  operation("/jobs/" + job.id, { action, value });
async function loadBundlebeeTemplate() {
  try {
    skillJson.value = JSON.stringify(
      await api("/skill-templates/bundlebee"),
      null,
      2,
    );
  } catch (e) {
    error.value = e.message;
  }
}
async function installSkill() {
  try {
    await api("/skills", JSON.parse(skillJson.value));
    skillJson.value = "";
    refresh();
  } catch (e) {
    error.value = e.message;
  }
}
async function saveMemory() {
  const d = await operation("/preferences", {
    id: memoryId.value,
    title: memoryTitle.value,
    content: memoryContent.value,
  });
  if (d) {
    memoryId.value = null;
    memoryTitle.value = "";
    memoryContent.value = "";
  }
}
async function saveKnowledge() {
  const d = await operation("/knowledge", {
    title: knowledgeTitle.value,
    content: knowledgeContent.value,
  });
  if (d) {
    knowledgeTitle.value = "";
    knowledgeContent.value = "";
  }
}
async function answerQuestion(q) {
  const answer = window.prompt(q.question + "\nYour confirmed preference:");
  if (answer)
    await operation("/questions/" + q.id, {
      title: q.question.slice(0, 100),
      content: answer,
    });
}
function fullscreen() {
  if (!document.fullscreenElement)
    document.documentElement
      .requestFullscreen?.()
      .catch((e) => (error.value = e.message));
  else document.exitFullscreen?.();
}
function stopMic() {
  clearTimeout(wakeTimer);
  if (recorder?.state === "recording") recorder.stop();
  stream?.getTracks().forEach((t) => t.stop());
  recording.value = false;
}
async function toggleMic() {
  if (recording.value) {
    recorder.stop();
    return;
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    chunks = [];
    recorder = new MediaRecorder(stream);
    recorder.ondataavailable = (e) => {
      if (e.data.size) chunks.push(e.data);
    };
    recorder.onstop = async () => {
      recording.value = false;
      stream.getTracks().forEach((t) => t.stop());
      const form = new FormData();
      form.append(
        "file",
        new Blob(chunks, { type: recorder.mimeType }),
        "audio.webm",
      );
      try {
        const r = await fetch("/api/voice/transcribe", {
          method: "POST",
          credentials: "include",
          body: form,
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail);
        if (d.text) {
          draft.value = d.text;
          await send();
        }
      } catch (e) {
        error.value = e.message;
      }
    };
    recorder.start();
    recording.value = true;
  } catch (e) {
    error.value = e.message;
  }
}
async function toggleWake() {
  if (wakeEnabled.value) {
    wakeEnabled.value = false;
    stopMic();
    return;
  }
  if (!state.value.authenticated) {
    error.value = "Sign in before enabling wake listening.";
    return;
  }
  wakeEnabled.value = true;
  await wakeCycle();
}
async function wakeCycle() {
  if (!wakeEnabled.value || disposed) return;
  if (busy.value || speaking.value) {
    wakeTimer = setTimeout(wakeCycle, 1000);
    return;
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const currentStream = stream;
    const r = new MediaRecorder(currentStream);
    recorder = r;
    const parts = [];
    r.ondataavailable = (e) => {
      if (e.data.size) parts.push(e.data);
    };
    r.onstop = async () => {
      currentStream.getTracks().forEach((t) => t.stop());
      if (!wakeEnabled.value || disposed) return;
      const form = new FormData();
      form.append("file", new Blob(parts, { type: r.mimeType }), "audio.webm");
      try {
        const response = await fetch("/api/voice/transcribe", {
          method: "POST",
          credentials: "include",
          body: form,
        });
        const d = await response.json();
        if (!response.ok) throw new Error(d.detail);
        const match = d.text.match(/\bjarvis\b[,:]?\s*(.*)/i);
        if (match?.[1] && !busy.value && !speaking.value) {
          draft.value = match[1];
          await send();
        }
      } catch (e) {
        error.value = e.message;
        wakeEnabled.value = false;
      }
      if (wakeEnabled.value) wakeTimer = setTimeout(wakeCycle, 500);
    };
    r.start();
    wakeTimer = setTimeout(() => {
      if (r.state === "recording") r.stop();
    }, 6000);
  } catch (e) {
    error.value = e.message;
    wakeEnabled.value = false;
  }
}
onMounted(async () => {
  refreshVoices();
  window.speechSynthesis?.addEventListener("voiceschanged", refreshVoices);
  refresh();
  polling = setInterval(refresh, 4000);
  ticking = setInterval(
    () => (clock.value = new Date().toLocaleTimeString("en-GB")),
    1000,
  );
  if (conversationId.value) {
    try {
      const d = await api("/history/" + conversationId.value);
      messages.value = d.messages;
    } catch {}
  }
});
onUnmounted(() => {
  disposed = true;
  speechRequest++;
  window.speechSynthesis?.removeEventListener("voiceschanged", refreshVoices);
  clearInterval(polling);
  clearInterval(ticking);
  wakeEnabled.value = false;
  stopMic();
  window.speechSynthesis?.cancel();
});
</script>
