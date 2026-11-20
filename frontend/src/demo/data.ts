// The demo data chunk: the fixtures and the URLs of the bundled images. Loaded on first use by the demo client
// (dynamic import), so it is a separate file in the build and the login page does not wait for it.
import fixtures from './fixtures/fixtures.gen'

const urls = import.meta.glob<string>('./fixtures/images/*.jpg', { eager: true, query: '?url', import: 'default' })

export const demoData = {
  fixtures,
  imageUrl(file: string): string {
    const url = urls[`./fixtures/images/${file}`]
    if (!url) throw new Error(`demo image missing: ${file} (re-run scripts/export_demo_fixtures.py export)`)
    return url
  },
}
