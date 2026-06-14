module.exports = async ({ github, context }) => {
  const owner = context.repo.owner;
  const repo = context.repo.repo;
  const title = "Penrice scraper failure";
  const labels = ["automation", "scraper-failure"];
  const streakPattern = /<!--\s*success-streak:(\d+)\s*-->/i;

  function getStreak(body) {
    const m = (body || "").match(streakPattern);
    return m ? parseInt(m[1], 10) : 0;
  }
  function setStreak(body, v) {
    const marker = `<!-- success-streak:${v} -->`;
    if (!body) return marker;
    return streakPattern.test(body)
      ? body.replace(streakPattern, marker)
      : body + "\n" + marker;
  }

  const existing = await github.rest.issues.listForRepo({
    owner, repo, state: "open", labels: labels.join(","), per_page: 100
  });
  const issue = existing.data.find(i => i.title === title);
  if (!issue) return;
  const next = getStreak(issue.body) + 1;
  if (next >= 2) {
    await github.rest.issues.createComment({
      owner, repo, issue_number: issue.number,
      body: "Auto-closing after 2 consecutive successful runs."
    });
    await github.rest.issues.update({
      owner, repo, issue_number: issue.number,
      state: "closed", body: setStreak(issue.body, next)
    });
  } else {
    await github.rest.issues.update({
      owner, repo, issue_number: issue.number,
      body: setStreak(issue.body, next)
    });
  }
};
