export const name = 'agent-team-role-policy';
export const inject = ['tools'];

const readTools = ['read', 'read_image', 'glob', 'grep'];
const webTools = ['web_search', 'web_fetch'];
const shell = process.platform === 'win32' ? 'pwsh' : 'bash';
const writeTools = [...readTools, 'edit', 'write', shell, 'job_list', 'job_output', 'job_kill'];
const deliveryChildTools = new Set([
  'delivery_list', 'delivery_mkdir', 'delivery_read', 'delivery_write', 'delivery_review_evidence',
]);
const roleTools = {
  coordinator: [
    ...writeTools, ...webTools, 'ask_user_question', 'skill', 'subagent', 'list_agents', 'send_message', 'wait_agent',
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

function parseStringList(value, field) {
  if (value === undefined) {
    return [];
  }
  if (!Array.isArray(value) || value.some(item => typeof item !== 'string' || item.length === 0)) {
    throw new Error(`Agent Teams role policy ${field} must be an array of non-empty strings.`);
  }
  return value;
}

export function apply(ctx, config = {}) {
  const { role, allowDeliveryTools, extraTools, extraToolPrefixes } = config ?? {};
  if (!Object.hasOwn(roleTools, role)) {
    throw new Error(`Unknown Agent Teams preset role: ${role}`);
  }
  if (allowDeliveryTools !== undefined && typeof allowDeliveryTools !== 'boolean') {
    throw new Error('Agent Teams role policy allowDeliveryTools must be a boolean.');
  }
  const deliveryAllowed = allowDeliveryTools ?? (role === 'coordinator');
  const allow = new Set([...roleTools[role], ...parseStringList(extraTools, 'extraTools')]);
  const prefixes = parseStringList(extraToolPrefixes, 'extraToolPrefixes');

  function isAllowed(name) {
    if (allow.has(name)) {
      return true;
    }
    if (deliveryAllowed && name.startsWith('delivery_') && !deliveryChildTools.has(name)) {
      return true;
    }
    return prefixes.some(prefix => name.startsWith(prefix));
  }

  // Preset tools and live agent tools can register in their own scopes.
  // Mask inherited global tools here and enforce the same policy at dispatch.
  const hidden = new Set();
  function hideInheritedTools() {
    const deny = ctx.tools.definitions().map(tool => tool.name)
      .filter(name => !isAllowed(name) && !hidden.has(name));
    if (deny.length > 0) {
      // restrict() emits tools/change synchronously.
      for (const name of deny) {
        hidden.add(name);
      }
      ctx.tools.restrict({ deny });
    }
  }
  ctx.on('tools/change', hideInheritedTools);
  hideInheritedTools();

  ctx.effect(() => ctx.tools.guard(({ name, arguments: args }) => {
    if (!isAllowed(name)) {
      return `Tool ${name} is unavailable to the Agent Teams ${role} role.`;
    }
    if (name === 'subagent' && !workerPresets.includes(args?.agent_preset)) {
      return 'Select an Agent Teams worker preset with agent_preset.';
    }
  }), 'agent-team-role-guard');
}
