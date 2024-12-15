__package__ = 'archivebox.base_models'

from typing import NamedTuple, Any, Union, Dict

import ulid
import uuid6
import hashlib
from urllib.parse import urlparse

from uuid import UUID
from typeid import TypeID            # type: ignore[import-untyped]
from datetime import datetime

from archivebox.misc.util import enforce_types


ABID_PREFIX_LEN = 4
ABID_SUFFIX_LEN = 26
ABID_LEN = 30
ABID_TS_LEN = 10
ABID_URI_LEN = 8
ABID_SUBTYPE_LEN = 2
ABID_RAND_LEN = 6

DEFAULT_ABID_PREFIX = 'obj_'

# allows people to keep their uris secret on a per-instance basis by changing the salt.
# the default means everyone can share the same namespace for URI hashes,
# meaning anyone who has a URI and wants to check if you have it can guess the ABID
DEFAULT_ABID_URI_SALT = '687c2fff14e3a7780faa5a40c237b19b5b51b089'


class ABID(NamedTuple):
    """
    e.g. ABID('obj_01HX9FPYTRE4A5CCD901ZYEBQE')
    """
    prefix: str            # e.g. obj_
    ts: str                # e.g. 01HX9FPYTR
    uri: str               # e.g. E4A5CCD9
    subtype: str           # e.g. 01
    rand: str              # e.g. ZYEBQE
    
    # salt: str = DEFAULT_ABID_URI_SALT

    def __getattr__(self, attr: str) -> Any:
        return getattr(self.ulid, attr)

    def __eq__(self, other: Any) -> bool:
        try:
            return self.ulid == other.ulid
        except AttributeError:
            return NotImplemented

    def __str__(self) -> str:
        return self.prefix + self.suffix

    def __len__(self) -> int:
        return len(self.prefix + self.suffix)

    @classmethod
    def parse(cls, buffer: Union[str, UUID, ulid.ULID, TypeID, 'ABID'], prefix=DEFAULT_ABID_PREFIX) -> 'ABID':
        assert buffer, f'Attempted to create ABID from null value {buffer}'

        buffer = str(buffer)
        if '_' in buffer:
            prefix, suffix = buffer.split('_')
        else:
            prefix, suffix = prefix.strip('_'), buffer

        assert len(prefix) == ABID_PREFIX_LEN - 1   # length without trailing _
        assert len(suffix) == ABID_SUFFIX_LEN, f'Suffix {suffix} from {buffer} was not {ABID_SUFFIX_LEN} chars long'

        return cls(
            prefix=abid_part_from_prefix(prefix),
            ts=suffix[0:10].upper(),
            uri=suffix[10:18].upper(),
            subtype=suffix[18:20].upper(),
            rand=suffix[20:26].upper(),
        )
    
    @property
    def uri_salt(self) -> str:
        return DEFAULT_ABID_URI_SALT

    @property
    def suffix(self):
        return ''.join((self.ts, self.uri, self.subtype, self.rand))
    
    @property
    def ulid(self) -> ulid.ULID:
        return ulid.parse(self.suffix)

    @property
    def uuid(self) -> UUID:
        return self.ulid.uuid

    @property
    def uuid6(self) -> uuid6.UUID:
        return uuid6.UUID(hex=self.uuid.hex)

    @property
    def typeid(self) -> TypeID:
        return TypeID.from_uuid(prefix=self.prefix.strip('_'), suffix=self.uuid6)

    @property
    def datetime(self) -> datetime:
        return self.ulid.timestamp().datetime



####################################################


@enforce_types
def uri_hash(uri: Union[str, bytes], salt: str=DEFAULT_ABID_URI_SALT) -> str:
    """
    https://example.com -> 'E4A5CCD9AF4ED2A6E0954DF19FD274E9CDDB4853051F033FD518BFC90AA1AC25' (example.com)
    """
    if isinstance(uri, bytes):
        uri_str: str = uri.decode()
    else:
        uri_str = str(uri)

    # only hash the domain part of URLs
    if '://' in uri_str:
        try:
            domain = urlparse(uri_str).netloc
            if domain:
                uri_str = domain
        except AttributeError:
            pass
    
    # the uri hash is the sha256 of the domain + salt
    uri_bytes = uri_str.encode('utf-8') + salt.encode('utf-8')

    return hashlib.sha256(uri_bytes).hexdigest().upper()

@enforce_types
def abid_part_from_prefix(prefix: str) -> str:
    """
    'snp_'
    """
    # if prefix is None:
    #     return 'obj_'

    prefix = prefix.strip('_').lower()
    assert len(prefix) == 3
    return prefix + '_'

@enforce_types
def abid_part_from_uri(uri: Any, salt: str=DEFAULT_ABID_URI_SALT) -> str:
    """
    'E4A5CCD9'     # takes first 8 characters of sha256(url)
    """
    uri = str(uri).strip()
    assert uri not in ('None', '')
    return uri_hash(uri, salt=salt)[:ABID_URI_LEN]

@enforce_types
def abid_part_from_ts(ts: datetime) -> str:
    """
    '01HX9FPYTR'   # produces 10 character Timestamp section of ulid based on added date
    """
    return str(ulid.from_timestamp(ts))[:ABID_TS_LEN]

@enforce_types
def ts_from_abid(abid: str) -> datetime:
    return ulid.parse(abid.split('_', 1)[-1]).timestamp().datetime

@enforce_types
def abid_part_from_subtype(subtype: str | int) -> str:
    """
    Snapshots have 01 type, other objects have other subtypes like wget/media/etc.
    Also allows us to change the ulid spec later by putting special sigil values here.
    """
    subtype = str(subtype)
    if len(subtype) == ABID_SUBTYPE_LEN:
        return subtype

    return hashlib.sha256(subtype.encode('utf-8')).hexdigest()[:ABID_SUBTYPE_LEN].upper()

@enforce_types
def abid_part_from_rand(rand: Union[str, UUID, None, int]) -> str:
    """
    'ZYEBQE'   # takes last 6 characters of randomness from existing legacy uuid db field
    """
    if rand is None:
        # if it's None we generate a new random 6 character hex string
        return str(ulid.new())[-ABID_RAND_LEN:]
    elif isinstance(rand, UUID):
        # if it's a uuid we take the last 6 characters of the ULID represation of it
        return str(ulid.from_uuid(rand))[-ABID_RAND_LEN:]
    elif isinstance(rand, int):
        # if it's a BigAutoInteger field we convert it from an int to a 0-padded string
        rand_str = str(rand)[-ABID_RAND_LEN:]
        padding_needed = ABID_RAND_LEN - len(rand_str)
        rand_str = ('0'*padding_needed) + rand_str
        return rand_str

    # otherwise treat it as a string, take the last 6 characters of it verbatim
    return str(rand)[-ABID_RAND_LEN:].upper()


@enforce_types
def abid_hashes_from_values(prefix: str, ts: datetime, uri: Any, subtype: str | int, rand: Union[str, UUID, None, int], salt: str=DEFAULT_ABID_URI_SALT) -> Dict[str, str]:
    return {
        'prefix': abid_part_from_prefix(prefix),
        'ts': abid_part_from_ts(ts),
        'uri': abid_part_from_uri(uri, salt=salt),
        'subtype': abid_part_from_subtype(subtype),
        'rand': abid_part_from_rand(rand),
        # 'salt': don't add this, salt combined with uri above to form a single hash
    }

@enforce_types
def abid_from_values(prefix: str, ts: datetime, uri: str, subtype: str, rand: Union[str, UUID, None, int], salt: str=DEFAULT_ABID_URI_SALT) -> ABID:
    """
    Return a freshly derived ABID (assembled from attrs defined in ABIDModel.abid_*_src).
    """

    abid = ABID(**abid_hashes_from_values(prefix, ts, uri, subtype, rand, salt=salt))
    assert abid.ulid and abid.uuid and abid.typeid, f'Failed to calculate {prefix}_ABID for ts={ts} uri={uri} subtyp={subtype} rand={rand}'
    return abid
