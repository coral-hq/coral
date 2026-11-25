import type { SimInput, SimScript } from "../api/generated/coralApi";

/** One result the person chose for a question the simulation asked. */
export interface SimulationAnswer {
  nodeId: string;
  kind: SimInput["kind"];
  value: string;
}

/**
 * The script for `answers`: one input per node and kind, in the order each first appears,
 * holding that node's values for that kind in the order they were given.
 */
export function scriptFromAnswers(answers: readonly SimulationAnswer[]): SimScript {
  const inputs = new Map<string, SimInput>();
  for (const { nodeId, kind, value } of answers) {
    const key = JSON.stringify([nodeId, kind]);
    const input = inputs.get(key);
    if (input) input.values.push(value);
    else inputs.set(key, { node_id: nodeId, kind, values: [value] });
  }
  return { inputs: [...inputs.values()] };
}

export const answersFromScript = (script: SimScript): SimulationAnswer[] =>
  (script.inputs ?? []).flatMap(({ node_id, kind, values }) =>
    values.map((value) => ({ nodeId: node_id, kind, value })),
  );
