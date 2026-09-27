# Domain redirect

The Vercel project `noumenon-redirect` forwards `noumenon.cc`, `www.noumenon.cc`
and all their paths to `https://github.com/petehottelet/noumenon` with an HTTP
308 redirect. The web explorer itself deploys from the repository root to the
`noumenon` project.

Deploy only this directory. It contains the redirect configuration and a
fallback link; nothing else in the repository is a deployment input.

```bash
cd infrastructure/redirect
vercel link --project noumenon-redirect --scope YOUR_VERCEL_SCOPE --yes
vercel deploy --prod --yes
```

Replace `YOUR_VERCEL_SCOPE` with the Vercel team that owns the project; the
CLI needs it when an account belongs to more than one team.

The domains must point to the DNS target shown in the Vercel project's Domains
settings. Validate the live `Location` response header after DNS changes. This
project is deployed independently of the explorer.
