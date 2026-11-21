export const name = 'agent-team-role-policy';
export const inject = ['tools'];

const readTools = ['read', 'glob', 'grep'];
const webTools = ['web_search', 'web_fetch'];
const shell = process.platform === 'win32' ? 'pwsh' : 'bash';
const writeTools = [...readTools, 'edit', 'write', shell, 'job_list', 'job_output', 'job_kill'];
const roleTools = {
  coordinator: [
    ...writeTools, ...webTools, 'skill', 'subagent', 'list_agents', 'send_message', 'wait_agent',
    'team_task_create', 'team_task_list', 'team_task_get', 'team_task_update',
  ],
  explorer: [...readTools, ...webTools],
  'design-agent': [...readTools, ...webTools],
  implementer: writeTools,
  ops: [...writeTools, ...webTools],
  reviewer: readTools,
};
const workerPresets = Object.keys(roleTools)
  .filter(role => role !== 'coordinator')
  .map(role => `agent-team-${role}`);

export function apply(ctx, { role }) {
  if (!Object.hasOwn(roleTools, role)) {
    throw new Error(`Unknown Agent Teams preset role: ${role}`);
  }
  const allow = roleTools[role];
  ctx.effect(() => ctx.tools.guard(({ name, arguments: args }) => {
    if (!allow.includes(name)) {
      return `Tool ${name} is unavailable to the Agent Teams ${role} role.`;
    }
    if (name === 'subagent' && !workerPresets.includes(args?.agent_preset)) {
      return 'Select an Agent Teams worker preset with agent_preset.';
    }
  }), 'agent-team-role-guard');
}
