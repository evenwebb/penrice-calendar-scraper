const fs = require("fs");
const crypto = require("crypto");

module.exports = async ({ github, context }) => {
  const owner = context.repo.owner;
  const repo = context.repo.repo;
  const title = "Penrice scraper failure";
  const labels = ["automation", "scraper-failure"];
  const runUrl = `https://github.com/${owner}/${repo}/actions/runs/${context.runId}`;

  let logSnippet = "";
  try {
    logSnippet = fs.readFileSync("logs/scraper.log", "utf8").slice(-8000);
  } catch (e) {
    console.error("Failed to read scraper log:", e.message);
  }

  const stableLines = logSnippet
    .split(/\r?\n/)
    .filter(l => /error|failed|traceback|exception|warning/i.test(l))
    .slice(-60).join("\n");
  const sig = crypto.createHash("sha256")
    .update(stableLines || logSnippet).digest("hex").slice(0, 16);
  const sigMarker = `<!-- failure-signature:${sig} -->`;
  const streakPattern = /<!--\s*success-streak:(\d+)\s*-->/i;

  function resetStreak(body) {
    const marker = "<!-- success-streak:0 -->";
    if (!body) return marker;
    return streakPattern.test(body) ? body.replace(streakPattern, marker) : body + "\n" + marker;
  }

  const body = [
    sigMarker,
    "The Penrice scraper workflow failed after configured retries.",
    "",
    `- Failure Signature: \`${sig}\``,
    `- Workflow: ${context.workflow}`,
    `- Job: ${context.job}`,
    `- Run: ${runUrl}`,
    `- Commit: ${context.sha}`,
    "",
    "### Log excerpt",
    "```text", (logSnippet || "No logs captured.").slice(-60000), "```",
  ].join("\n");

  const existing = await github.rest.issues.listForRepo({
    owner, repo, state: "all", labels: labels.join(","), per_page: 100
  });

  let issue = existing.data.find(i => i.title === title && (i.body || "").includes(sigMarker));
  if (!issue) {
    for (const i of existing.data) {
      if (i.title !== title) continue;
      const comments = await github.rest.issues.listComments({
        owner, repo, issue_number: i.number, per_page: 100
      });
      if (comments.data.some(c => (c.body || "").includes(sigMarker))) {
        issue = i; break;
      }
    }
  }

  if (issue) {
    if (issue.state === "closed") {
      await github.rest.issues.update({ owner, repo, issue_number: issue.number, state: "open" });
    }
    await github.rest.issues.update({ owner, repo, issue_number: issue.number, body: resetStreak(issue.body) });
  } else {
    const match = existing.data.find(i => i.title === title);
    if (match) {
      await github.rest.issues.createComment({ owner, repo, issue_number: match.number, body });
    } else {
      await github.rest.issues.create({ owner, repo, title, body: resetStreak(body), labels });
    }
  }
};
