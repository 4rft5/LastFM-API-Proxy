# LastFM-API-Proxy
An open source reimplementation of the LastFM API that can be hosted locally.

# Information
This is a local implementation of the LastFM API intended for use with Multi-Scrobbler and Navidrome.

As of right now, Navidrome does not directly scrobble plays reliably when offline, causing issues when either using third party clients or apps. However, offline scrobbles are correctly passed when using the built in LastFM (and potentially ListenBrainz) APIs in Navidrome.

This container is intended to be ran locally to intercept those API calls to a local database, rather than needing an external (or two) LastFM account(s).

Because Navidrome and Multi-Scrobbler both communicate directly with LastFM (and as far as I know, this is the first LastFM API Proxy), there is no configurable URL section for either, so a little network trickery needs to be done in order for this container to work. You can read the `How It Works` section for more information.

<details>
<summary>How It Works</summary>

The Proxy container generates and makes use of a certificate that when used with changed hosts on Navidrome and Multi-Scrobbler, tricks them into thinking they are communicating with the real LastFM API (`ws.audioscrobbler.com`). Unfortunately because of this, the Proxy container needs ports 80 and 443 open to receive API calls. This might be able to be rectified with a reverse proxy or Docker network, but I haven't looked into them.

Because of this interception, scrobbles from Navidrome are instead sent to the container and saved to its database, allowing for Multi-Scrobbler to check it periodically for new scrobbles. Other unrelated API calls are forwarded to the real LastFM client (like if you want to scrobble to an actual LastFM account).

If Navidrome and Multi-Scrobbler implemented the ability to configure a custom URL for LastFM integrations, this wouldn't need to be as complex.
</details>

<details>
<summary>Disclaimer</summary>
This container was partially written with Claude.ai as part of a college Python assignment to use AI in part to make an API "do something useful". I wouldn't recommend exposing this container to the open internet.
</details>

# Installation
## LastFM-Proxy
1. Download the source code from this repository and place it onto your host.
2. Configure the `docker-compose.yml` file with API keys of your choosing (You can leave them as default if you want, just remember for <a href="https://www.navidrome.org/docs/usage/configuration-options/#advanced-configuration">Navidrome</a> and <a href="https://foxxmd.github.io/multi-scrobbler/docs/configuration/#lastfm-source">Multi-Scrobbler</a> to set with the same API keys as in compose.)
3. Run `docker compose up -d` to launch the container. A certs folder will be made with `lastfm-proxy.crt` inside.
4. Note the IP of the host where the container is running as well as the path of the certificate for configuring the containers below.

## Navidrome
1. Set the ENV variables `ND_LASTFM_APIKEY` and `ND_LASTFM_SECRET` to the same API keys in the Proxy's docker-compose.
2. Add the cert to the compose volumes section:
```
- /path/to/lastfm-proxy.crt:/usr/local/share/ca-certificates/lastfm-proxy.crt:ro
```
4. Add the entrypoint in Compose to add the cert to Navidrome:
```
entrypoint: sh -c "apk add --no-cache ca-certificates && update-ca-certificates && /app/navidrome"
```
6. Lastly, add the new host for `ws.audioscrobbler.com` with the host IP of where the Proxy is: 
```
    extra_hosts:
      - "ws.audioscrobbler.com:192.168.1.2"
```
5. Start Navidrome with `docker compose up -d` and enable `Scrobble to LastFM`. This should launch a callback to the actual LastFM site in a new tab. This can be accepted and closed.

## Multi-Scrobbler
1. Create a <a href="https://foxxmd.github.io/multi-scrobbler/docs/configuration/#lastfm-source">LastFM Source</a> and set the API keys to the same as Navidrome and the Proxy.
2. Add the ENV varaible for the cert to compose:
```
- NODE_EXTRA_CA_CERTS=/usr/local/share/ca-certificates/lastfm-proxy.crt
```
2. Add the cert to the compose volumes section:
```
- /path/to/lastfm-proxy.crt:/usr/local/share/ca-certificates/lastfm-proxy.crt:ro
```
4. Add the new host for `ws.audioscrobbler.com`: 
```
    extra_hosts:
      - "ws.audioscrobbler.com:192.168.1.2"
```
4. Start Multi-Scrobbler with `docker-compose up -d` and verify the LastFM Source is available. You will need to authenticate with another actual LastFM callback which can be accepted and closed.

# Testing

You can verify that Multi-Scrobbler is accessing the proxy by checking the Proxy's logs. If `GET /2.0 - method: user.getRecentTracks - api_key_match: True` appears, this means that Multi-Scrobbler is checking it for new listens.

Try playing a song to completion in Navidrome. You should see Navidrome Docker logs akin to:
```
time="2025-10-27T10:22:08-06:00" level=info msg="Now Playing" artist=Deftones player="NavidromeUI [Firefox/macOS]" position=0 requestId=f6a3ed1eed88/k5Yfm6Hvxb-004829 title="The Chauffeur (2005 Remaster)" user=4rft5

time="2025-10-27T10:24:51-06:00" level=info msg=Scrobbled artist=Deftones requestId=f6a3ed1eed88/k5Yfm6Hvxb-004850 timestamp="2025-10-27 10:22:08.123 -0600 MDT" title="The Chauffeur (2005 Remaster)" user=4rft5
```

When the `msg=Scrobbled` appears, check the Proxy logs. There should be a `POST /2.0/ - method: track.scrobble - api_key_match: True` hidden amongst the constant checks from Multi-Scrobbler. This means that the scrobble was received from Navidrome and saved to the database.

Within a couple seconds, Multi-Scrobbler should pick up that there is a new scrobble and add it in the UI and logs: 

```
[2025-10-27 10:25:08.603 -0600] INFO   : [App] [Sources] [Lastfm - LastFM-Proxy] Discovered => Deftones - The Chauffeur (2005 Remaster) @ 2025-10-27T10:22:08-06:00 (S)
```

In the Multi-Scrobbler ui, under `LastFM (Source)` should now be "Tracks Discovered:" which can be clicked and display the scrobbles from the Proxy. As they are now in Multi-Scrobbler, they can be forwarded wherever else you have configured in Multi-Scrobbler.

# Contributions

Contributions to the Proxy would be very welcome. I'm unsure at this point what could be added, but would welcome PRs with new features if anyone wants to submit them.

# Troubleshooting

1. Ensure that the certificate is properly configured in the compose files volume section for Multi-Scrobbler and Navidrome.
2. Make sure that the IP in custom_hosts is set to the IP of the host where the container is running.
3. Make sure ports 80 and 443 are not in use by any other service on the host. I'd love to change this (and probably could with a reverse proxy, but haven't yet.)
4. Ensure the custom-set API credentials are the same across the Proxy, Navidrome and Multi-Scrobbler.

If all else fails, you can open an issue here. Please provide logs from everything to help me better help you.
