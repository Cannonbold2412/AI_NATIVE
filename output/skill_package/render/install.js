const fs = require("fs");
const os = require("os");
const path = require("path");

const skillName = "render";
const claudeRoot = path.join(os.homedir(), ".claude");
const source = path.join(__dirname, "claude", "skills", skillName);
const target = path.join(claudeRoot, "skills", skillName);
const claudeCandidates = [path.join(claudeRoot, "CLAUDE.md"), path.join(claudeRoot, "Claude.md")];
const claudePath = claudeCandidates.find((candidate) => fs.existsSync(candidate)) || claudeCandidates[0];
const renderBlock = "# render\n\n* **render** (~/.claude/skills/render/SKILL.md) - Render automation workflows. Trigger: /render\n\nWhen the user:\n\n* mentions render automation tasks\n* OR uses /render\n\nInvoke:\nskill: \"render\"";

console.log(`Source skill path: ${source}`);
console.log(`Target skill path: ${target}`);
console.log(`CLAUDE.md path: ${claudePath}`);
fs.mkdirSync(path.dirname(target), { recursive: true });
fs.cpSync(source, target, { recursive: true, force: true });
const existing = fs.existsSync(claudePath) ? fs.readFileSync(claudePath, "utf8") : "";
if (!existing.includes(`# ${skillName}`) && !existing.includes(`skill: \"${skillName}\"`)) {
  const next = existing.trimEnd() ? `${existing.trimEnd()}\n\n${renderBlock}\n` : `${renderBlock}\n`;
  fs.mkdirSync(path.dirname(claudePath), { recursive: true });
  fs.writeFileSync(claudePath, next, "utf8");
  console.log(`Registered ${skillName} in ${claudePath}`);
} else {
  console.log(`${skillName} block already present in ${claudePath}`);
}
