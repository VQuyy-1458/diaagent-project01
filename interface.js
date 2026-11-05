const theme = document.querySelector("#theme");
const root = document.documentElement;
let dark = localStorage.getItem("diaagent-theme") === "dark";
function applyTheme() {
    root.dataset.theme = dark ? "dark" : "light";
    theme.setAttribute("aria-pressed", String(dark));
}
if (theme) {
    applyTheme();
    theme.addEventListener("click", () => {
        dark = !dark;
        localStorage.setItem("diaagent-theme", dark ? "dark" : "light");
        applyTheme();
    });
}

const form = document.querySelector("#knowledge-form");
const log = document.querySelector("#conversation");
if (form && log) {
    const storageKey = "diaagent-conversation";
    let turns = [];
    try {
        const saved = JSON.parse(localStorage.getItem(storageKey) || "[]");
        if (Array.isArray(saved)) turns = saved.slice(-12);
    } catch {}
    const exportButton = document.querySelector("#export-chat");
    const clearButton = document.querySelector("#clear-chat");

    function render() {
        log.replaceChildren();
        for (const turn of turns) {
            const card = document.createElement("article");
            const title = document.createElement("h3");
            const answer = document.createElement("p");
            const sources = document.createElement("ul");
            title.textContent = turn.question;
            answer.textContent = turn.answer;
            for (const source of turn.sources || []) {
                if (!/^https:\/\//.test(source.url)) continue;
                const item = document.createElement("li");
                const link = document.createElement("a");
                link.href = source.url;
                link.textContent = source.title;
                item.append(link);
                sources.append(item);
            }
            card.append(title, answer, sources);
            log.append(card);
        }
        exportButton.disabled = clearButton.disabled = !turns.length;
    }

    form.addEventListener("submit", async event => {
        event.preventDefault();
        const payload = new URLSearchParams(new FormData(form));
        const submit = form.querySelector('button[type="submit"]');
        const status = document.querySelector("#chat-status");
        const previous = turns.at(-1);
        if (previous?.context) payload.set("context", previous.context);
        submit.disabled = true;
        status.textContent = "Đang tìm nguồn…";
        try {
            const response = await fetch(form.action, {method: "POST", body: payload});
            if (!response.ok) throw new Error();
            const doc = new DOMParser().parseFromString(await response.text(), "text/html");
            const result = doc.querySelector("#current-answer");
            if (!result) throw new Error();
            document.querySelector("#answer-slot").replaceChildren(result);
            turns.push({
                question: payload.get("question"),
                answer: result.querySelector(".answer-text").textContent,
                context: result.dataset.context,
                sources: [...result.querySelectorAll("a")].map(a => ({title:a.textContent,url:a.href})),
            });
            turns = turns.slice(-12);
            localStorage.setItem(storageKey, JSON.stringify(turns));
            render();
            status.textContent = "Đã trả lời.";
        } catch {
            status.textContent = "Không tải được câu trả lời. Vui lòng thử lại.";
        } finally {
            submit.disabled = false;
        }
    });
    clearButton.addEventListener("click", () => {
        turns = [];
        localStorage.removeItem(storageKey);
        document.querySelector("#answer-slot").replaceChildren();
        render();
    });
    exportButton.addEventListener("click", () => {
        const body = turns.map(turn => [turn.question, turn.answer,
            ...(turn.sources || []).map(source => source.url)].join("\n")).join("\n\n");
        const url = URL.createObjectURL(new Blob([body], {type:"text/plain;charset=utf-8"}));
        const link = document.createElement("a");
        link.href = url;
        link.download = "diaagent-hoi-dap.txt";
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    render();
}

