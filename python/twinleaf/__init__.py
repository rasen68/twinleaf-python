from twinleaf import _twinleaf

class Device(_twinleaf._Device):
    """ Primary TIO interface with sensor object """
    def __new__(cls, url=None, route=None, announce=False, instantiate=True):
        device = super().__new__(cls, url, route)
        return device

    def __init__(self, url=None, route=None, announce=False, instantiate=True):
        super().__init__()
        if instantiate:
            self._instantiate_rpcs()
            self._instantiate_samples(announce)

    def _rpc_int(self, name: str, size: int, signed: bool, value: int | None = None) -> int:
        """ Use struct to send int-typed RPCs """
        import struct
        match size, signed:
            case 1, True: fstr = '<b'
            case 2, True: fstr = '<h'
            case 4, True: fstr = '<i'
            case 8, True: fstr = '<q'
            case 1, False: fstr = '<B'
            case 2, False: fstr = '<H'
            case 4, False: fstr = '<I'
            case 8, False: fstr = '<Q'
        payload = b'' if value is None else struct.pack(fstr, value)
        rep = self._rpc(name, payload)
        val = struct.unpack(fstr, rep)[0]
        return val

    def _rpc_float(self, name: str, size: int, value: float | None = None) -> float:
        """ Use struct to send float-typed RPCs """
        import struct
        fstr = '<f' if (size == 4) else '<d'
        payload = b'' if value is None else struct.pack(fstr, value)
        rep = self._rpc(name, payload)
        val = struct.unpack(fstr, rep)[0]
        return val

    def _instantiate_rpcs(self):
        """ Set up Device.samples, then recursively instantiate RPCs """
        self._registry = self._rpc_registry()
        self.settings = _RpcSurvey('settings', self)
        self._instantiate_rpcs_recursive(self.settings)

    def _instantiate_rpcs_recursive(self, parent, prefix=''):
        """ Get children from registry, setattr them, then recurse """
        for child_name in self._registry.children_of(prefix):
            full_path = f'{prefix}.{child_name}' if prefix else child_name
            rpc = self._registry.find(full_path)
            attr_name = '_rpc' if child_name == 'rpc' else child_name

            if rpc is not None:
                child = _Rpc(rpc, self)
            else:
                child = _RpcSurvey(attr_name, self)
            setattr(parent, attr_name, child)
            self._instantiate_rpcs_recursive(child, full_path)

    def _samples_dict(self, n: int = 1, stream: str = "", columns: list[str] = []):
        samples = list(self._samples(n, stream=stream, columns=columns))
        # Bin into streams
        streams = {}
        for line in samples:
            stream_id = line.pop("stream", None)
            if stream_id not in streams:
                streams[stream_id] = { "stream": stream_id }
            for key, value in line.items():
                if key not in streams[stream_id]:
                    streams[stream_id][key] = []
                streams[stream_id][key].append(value)
        return streams

    def _samples_list(self, n: int = 1, stream: str = "", columns: list[str] = [], time_column = True, title_row = True):
        streams = self._samples_dict(n, stream, columns)
        # Convert to list with rows of data. Not super happy about how inefficient this is. 
        if len(streams.items()) > 1:
            raise NotImplementedError("Stream concatenation not yet implemented for two different streams")
        stream = list(streams.values())[0]
        stream.pop('stream')
        if not time_column:
            stream.pop('time')
        data_columns = [column for column in stream.values() ]
        data_rows = [list(row) for row in zip(*data_columns)]
        if title_row:
            column_names = list(stream.keys());
            data_rows.insert(0,column_names)
        return data_rows

    def _instantiate_samples(self, announce: bool=False):
        metadata = self._get_metadata()
        if announce:
            dev_meta = metadata['device']
            print(f"{dev_meta['name']} ({dev_meta['serial_number']}) [{dev_meta['firmware_hash']}]")

        streams_flattened = []
        for stream, value in metadata['streams'].items():
            for column_name in value['columns'].keys():
                streams_flattened.append(stream+"."+column_name)

        # All samples
        self.samples = _SamplesDict(self, "samples", stream="", columns=[])

        for stream_column in streams_flattened:
            stream, *prefix, mname = stream_column.split(".")
            parent = self.samples

            # All samples for this stream
            if not hasattr(parent, stream):
                setattr(parent, stream, _SamplesList(self, name=stream, stream=stream, columns=[]))
            parent = getattr(parent, stream)

            # Wildcard columns within stream
            stream_prefix = ""
            for token in prefix:
                stream_prefix += "." + token
                if not hasattr(parent, token):
                    setattr(parent, token, _SamplesList(self, token, stream, columns=[stream_prefix[1:]+".*"]))
                parent = getattr(parent, token)

            # Specific stream samples
            stream, column_name = stream_column.split(".",1)
            setattr(parent, mname, _SamplesList(self, mname, stream, columns=[column_name]))

    def _interact(self):
        imported_objects = {}
        imported_objects["tl"] = self
        try:
            import IPython
            IPython.embed(
                user_ns=imported_objects, 
                banner1="", 
                banner2="", # Use   : {self._shortname}.<tab>
                exit_msg="",
                enable_tip=False)
        except ImportError:
            import code
            repl = code.InteractiveConsole(locals=imported_objects)
            repl.interact(
                banner = "", 
                exitmsg = "")

type _rpc_type = int | float | str | bytes | None
class _RpcNode:
    """ Base class for RPCs and surveys in the device tree """
    def __init__(self, name, device: Device):
        self.__name__ = name
        self._device = device

    def survey(self) -> dict[str, _rpc_type]:
        """ Recursively collect all readable RPC values in this subtree """
        results = {}
        for name, attr in self.__dict__.items():
            if isinstance(attr, _RpcNode):
                # Check if it's an RPC that should be read
                if isinstance(attr, _RpcBase):
                    if attr._readable and attr._data_type is not None:
                        results[attr.__name__] = attr()

                # Recursively survey children (works for both Rpc and Survey)
                results |= attr.survey()
        return results

class _RpcBase(_RpcNode):
    """ Internal base class for RPCs """
    def __init__(self, pyrpc: _twinleaf._Rpc, device: Device):
        super().__init__(pyrpc.name, device)
        self._size_bytes = pyrpc.size_bytes
        self._readable   = pyrpc.readable
        self._writable   = pyrpc.writable
        match pyrpc.type_str:
            case _ if _.startswith('i'): self._data_type, self._signed = int, True
            case _ if _.startswith('u'): self._data_type, self._signed = int, False
            case _ if _.startswith('f'): self._data_type = float
            case _ if _.startswith('s'): self._data_type = str
            case '' if self._size_bytes == 0: self._data_type = None
            case other: self._data_type = bytes

    def _call_with_arg(self, arg=None) -> _rpc_type:
        match self._data_type:
            case _ if _ is int:
                return self._device._rpc_int(self.__name__, self._size_bytes, self._signed, arg)
            case _ if _ is float:
                return self._device._rpc_float(self.__name__, self._size_bytes, arg)
            case _ if _ is str:
                return self._device._rpc(self.__name__, arg.encode()).decode()
            case _ if _ is bytes:
                return self._device._rpc(self.__name__, arg)
            case None:
                return self._device._rpc(self.__name__, b'')
            case other:
                raise TypeError(f"Invalid RPC type {other}, RPC types must be {_rpc_type}")

    def _call(self) -> _rpc_type:
        match self._data_type:
            case _ if _ is int:
                return self._device._rpc_int(self.__name__, self._size_bytes, self._signed)
            case _ if _ is float:
                return self._device._rpc_float(self.__name__, self._size_bytes)
            case _ if _ is str:
                return self._device._rpc(self.__name__, b'').decode()
            case _ if _ is bytes | None:
                return self._device._rpc(self.__name__, b'')
            case other:
                raise TypeError(f"Invalid RPC type {other}, RPC types must be {_rpc_type}")

class _RpcSurveyBase(_RpcNode):
    """ Internal class for RPC surveys """
    def __init__(self, name: str, device: Device):
        super().__init__(name, device)

    def __call__(self):
        return self.survey()

def _Rpc(pyrpc: _twinleaf._Rpc, device: Device) -> _RpcNode:
    """ Factory function that creates an RPC with appropriate __call__ signature """
    if pyrpc.writable:
        def __call__(self, arg=None) -> _rpc_type:
            if arg is None:
                return self._call()
            else:
                return self._call_with_arg(arg)
    else:
        def __call__(self) -> _rpc_type:
            return self._call()

    cls = type('Rpc', (_RpcBase,), {'__call__': __call__})
    return cls(pyrpc, device)

def _RpcSurvey(name: str, device: Device) -> _RpcNode:
    """ Factory function that creates an RPC survey """
    cls = type('Survey', (_RpcSurveyBase,), {})
    return cls(name, device)

# Samples classes
class _SamplesBase:
    """ Base class for sample objects """
    def __init__(self, device: Device, name: str, stream: str, columns: list[str]):
        self._device = device
        self.__name__ = name
        self._stream = stream
        self._columns = columns

class _SamplesDictBase(_SamplesBase):
    """ Returns samples as dict keyed by stream_id """
    def __call__(self, n: int = 1, **kwargs):
        return self._device._samples_dict(n, self._stream, self._columns, **kwargs)

class _SamplesListBase(_SamplesBase):
    """ Returns samples as list for single stream """
    def __call__(self, n: int = 1, **kwargs):
        return self._device._samples_list(n, self._stream, self._columns, **kwargs)

def _SamplesDict(device: Device, name: str, stream: str = "", columns: list[str] = []):
    """ Factory function that creates a sample dict """
    return _SamplesDictBase(device, name, stream, columns)

def _SamplesList(device: Device, name: str, stream: str = "", columns: list[str] = []):
    """ Factory function that creates a sample list """
    return _SamplesListBase(device, name, stream, columns)
