import dagre from '@dagrejs/dagre'

export const NODE_W = 244

export function estimateHeight(n) {
  if (n.measured?.height) return n.measured.height
  if (n.type === 'models') return 60 + Math.min(n.data.models.length, 6) * 24
  const node = n.data.node
  let h = 122
  if (node.preview || (node.role === 'output' && node.results?.length)) h += 116
  return h
}

// Left-to-right layout following the data flow
export function autoLayout(nodes, edges) {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: 40, ranksep: 64, marginx: 20, marginy: 20 })
  g.setDefaultEdgeLabel(() => ({}))
  nodes.forEach((n) => g.setNode(n.id, { width: NODE_W, height: estimateHeight(n) }))
  edges.forEach((e) => { if (g.hasNode(e.source) && g.hasNode(e.target)) g.setEdge(e.source, e.target) })
  dagre.layout(g)
  const pos = {}
  nodes.forEach((n) => {
    const p = g.node(n.id)
    pos[n.id] = { x: Math.round(p.x - NODE_W / 2), y: Math.round(p.y - p.height / 2) }
  })
  return pos
}
