# Single sign-on and identity

## Supported protocols

Operator workstations sign in through SAML 2.0 or OpenID Connect. The identity provider must
publish a metadata document and rotate its signing certificate at least once a year.

## Roles

Three roles exist: operator, supervisor and administrator. Role assignments are taken from a
group claim in the token; users without a mapped group are refused.

## Session lifetime

Operator sessions expire after twelve hours of inactivity, supervisor sessions after eight.
