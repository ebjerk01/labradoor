export default { id: 'badpeer', objects: (d, ctx) => [{ id: 'x', a: ctx.peer('leaf'), b: ctx.peer('other'), c: ctx.via(`stranger`) }] };
