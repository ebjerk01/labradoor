import { helper } from '../../good/ui/util.js';
export default { id: 'badcross', load: () => import('../../leaf/ui/index.js').then(() => helper()) };
