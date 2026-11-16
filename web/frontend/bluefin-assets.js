import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { createHash } from 'node:crypto'

const directory = fileURLToPath(new URL('../bluefin-preview/', import.meta.url))
const files = ['theme.js', 'base.css', 'style.css', 'app.js', 'app-shell.js', 'i18n.js', 'analytics.js', 'views-update.js', 'bootstrap.js']

export function bluefinAssets() {
  return {
    name: 'bluefin-assets',
    configureServer(server) {
      server.watcher.add(directory)
      server.watcher.on('change', path => {
        if (path.startsWith(directory)) server.ws.send({ type: 'full-reload' })
      })
      server.middlewares.use('/bluefin', (request, response, next) => {
        const name = (request.url || '').split('?')[0].replace(/^\//, '')
        if (!files.includes(name)) return next()
        response.setHeader('Content-Type', name.endsWith('.css') ? 'text/css; charset=utf-8' : 'application/javascript; charset=utf-8')
        response.setHeader('Cache-Control', 'no-store')
        response.end(readFileSync(directory + name))
      })
    },
    transformIndexHtml: {
      order: 'post',
      handler() {
        const version = createHash('sha256').update(files.map(name => readFileSync(directory + name)).join('')).digest('hex').slice(0, 10)
        return files.map(name => name.endsWith('.css')
          ? { tag: 'link', attrs: { rel: 'stylesheet', href: `/bluefin/${name}?v=${version}` }, injectTo: 'head' }
          : { tag: 'script', attrs: { src: `/bluefin/${name}?v=${version}` }, injectTo: name === 'theme.js' ? 'head-prepend' : 'body' })
      },
    },
    generateBundle() {
      for (const name of files) this.emitFile({ type: 'asset', fileName: `bluefin/${name}`, source: readFileSync(directory + name) })
    },
  }
}
