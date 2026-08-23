export const ZONES = [
  ['front', 'Avant'], ['front_left', 'Avant gauche'], ['left', 'Côté gauche'],
  ['rear_left', 'Arrière gauche'], ['rear', 'Arrière'], ['rear_right', 'Arrière droit'],
  ['right', 'Côté droit'], ['front_right', 'Avant droit'], ['wheel', 'Roue'],
] as const

export function zoneLabel(zone: string): string {
  return ZONES.find(([value]) => value === zone)?.[1] ?? zone
}
