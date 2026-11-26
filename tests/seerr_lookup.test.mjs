// Seerr's Ctrl-K lookup keeps only titles that match what was typed (TMDB answers every word with films).
import assert from 'node:assert/strict';
import test from 'node:test';
import { rankTitles } from '../modules/seerr/ui/sr.js';

const mk = (title, pop = 1, type = 'movie') => ({ title, pop, type });
const titles = (r) => r.map((x) => x.title);

test('exact title first, then prefix, then word match; junk is dropped', () => {
  const r = rankTitles('dune', [mk('Arrakis Wars', 99), mk('Dune: Part Two', 50), mk('Dune', 10), mk('The Dune Sea', 5), mk('Something Else', 100)]);
  assert.deepEqual(titles(r), ['Dune', 'Dune: Part Two', 'The Dune Sea']);
});
test('every typed word must match', () => {
  const r = rankTitles('breaking bad', [mk('Breaking Bad', 1, 'tv'), mk('Breaking Dawn', 90), mk('Bad Boys', 80)]);
  assert.deepEqual(titles(r), ['Breaking Bad']);
});
test('accents and punctuation do not matter; popularity breaks ties', () => {
  const r = rankTitles('amelie', [mk('Amélie', 3), mk('Amelie of Ham', 2)]);
  assert.equal(r[0].title, 'Amélie');
  assert.equal(rankTitles('spider man', [mk('Spider-Man', 5), mk('Spider-Man 2', 9)])[0].title, 'Spider-Man');
  assert.equal(rankTitles('spider', [mk('Spider-Man', 5), mk('Spider-Man 2', 9)])[0].title, 'Spider-Man 2');
});
test('nothing matches → empty; empty query → empty', () => {
  assert.deepEqual(rankTitles('zzzz', [mk('Dune')]), []);
  assert.deepEqual(rankTitles('  ', [mk('Dune')]), []);
});
