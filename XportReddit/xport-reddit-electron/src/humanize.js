function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Sleep for baseSeconds +/- variance * baseSeconds. */
async function humanDelay(baseSeconds, variance = 0.3) {
  const lo = baseSeconds * (1 - variance);
  const hi = baseSeconds * (1 + variance);
  const delay = lo + Math.random() * (hi - lo);
  await sleep(delay * 1000);
}

function randInt(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function randFloat(min, max) {
  return min + Math.random() * (max - min);
}

const TYPO_MAP = {
  a: ['s', 'q', 'w'], b: ['v', 'n', 'g'], c: ['x', 'v', 'd'],
  d: ['s', 'f', 'e'], e: ['w', 'r', 'd'], f: ['d', 'g', 'r'],
  g: ['f', 'h', 't'], h: ['g', 'j', 'y'], i: ['u', 'o', 'k'],
  j: ['h', 'k', 'u'], k: ['j', 'l', 'i'], l: ['k', 'o', 'p'],
  m: ['n', 'j', 'k'], n: ['b', 'm', 'h'], o: ['i', 'p', 'l'],
  p: ['o', 'l'], q: ['w', 'a'], r: ['e', 't', 'f'],
  s: ['a', 'd', 'w'], t: ['r', 'y', 'g'], u: ['y', 'i', 'j'],
  v: ['c', 'b', 'f'], w: ['q', 'e', 's'], x: ['z', 'c', 's'],
  y: ['t', 'u', 'h'], z: ['x', 'a'],
};

/** Type text into a Playwright page's focused element with human-like timing. */
async function humanType(page, text, { minDelay = 0.05, maxDelay = 0.15, withTypos = false } = {}) {
  for (const char of text) {
    if (withTypos && TYPO_MAP[char.toLowerCase()] && Math.random() < 0.05) {
      const candidates = TYPO_MAP[char.toLowerCase()];
      let wrong = candidates[randInt(0, candidates.length - 1)];
      if (char !== char.toLowerCase()) wrong = wrong.toUpperCase();
      await page.keyboard.type(wrong);
      await sleep(randFloat(minDelay, maxDelay) * 1000);
      await sleep(randFloat(0.1, 0.3) * 1000);
      await page.keyboard.press('Backspace');
      await sleep(randFloat(0.05, 0.1) * 1000);
      await page.keyboard.type(char);
      await sleep(randFloat(minDelay, maxDelay) * 1000);
    } else {
      await page.keyboard.type(char);
      await sleep(randFloat(minDelay, maxDelay) * 1000);
    }

    if (Math.random() < 0.15) await sleep(randFloat(0.2, 0.6) * 1000);
  }

  if (Math.random() < 0.3) await sleep(randFloat(0.3, 0.8) * 1000);
}

module.exports = { sleep, humanDelay, humanType, randInt, randFloat };
