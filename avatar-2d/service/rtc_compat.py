"""Keep half-trickle ICE open for browsers with only private mDNS candidates."""


def prepare_local_offer(params):
    lines=params.get('sdp','').splitlines()
    candidates=[line.split() for line in lines if line.startswith('a=candidate:')]
    mdns_only=bool(candidates) and all(len(parts)>4 and parts[4].lower().rstrip('.').endswith('.local') for parts in candidates)
    if not mdns_only:
        return params,False
    # Firefox hides host addresses behind mDNS before microphone authorization.
    # When Windows cannot resolve those names, aioice's end-of-candidates handling
    # prunes the ICE component BEFORE gathering local candidates. Leave this
    # half-trickle negotiation open so it can advertise local candidates and learn
    # the peer-reflexive address from the browser's authenticated ICE checks.
    # Do not disable browser privacy, invent peer IPs, or change ICE credentials.
    filtered=[line for line in lines if line!='a=end-of-candidates']
    return {**params,'sdp':'\r\n'.join(filtered)+'\r\n'},True


class OfferPayload:
    def __init__(self,params):self.params=params
    async def json(self):return self.params
