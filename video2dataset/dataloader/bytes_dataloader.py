"""video dataset creation"""
import logging
import webdataset as wds

from webdataset.tariterators import base_plus_ext, url_opener, tar_file_expander, valid_sample


def filter_no_caption_or_no_video(sample):
    has_caption = "txt" in sample
    has_video = "mp4" in sample
    return has_caption and has_video


def group_by_keys_nothrow(
    data, keys=base_plus_ext, lcase=True, suffixes=None, handler=None
):  # pylint: disable=unused-argument
    """Return function over iterator that groups key, value pairs into samples.
    :param keys: function that splits the key into key and extension (base_plus_ext)
    :param lcase: convert suffixes to lower case (Default value = True)
    """
    current_sample = None
    for filesample in data:
        assert isinstance(filesample, dict)
        fname, value = filesample["fname"], filesample["data"]
        prefix, suffix = keys(fname)
        if prefix is None:
            continue
        if lcase:
            suffix = suffix.lower()
        # FIXME webdataset version throws if suffix in current_sample, but we have a potential for
        #  this happening in the current LAION400m dataset if a tar ends with same prefix as the next
        #  begins, rare, but can happen since prefix aren't unique across tar files in that dataset
        if (
            current_sample is None
            or prefix != current_sample["__key__"]
            or suffix in current_sample  # pylint: disable=unsupported-membership-test
        ):
            if valid_sample(current_sample):
                yield current_sample
            current_sample = dict(__key__=prefix, __url__=filesample["__url__"])
        if suffixes is None or suffix in suffixes:
            current_sample[suffix] = value
    if valid_sample(current_sample):
        yield current_sample


def log_and_continue(exn):
    """Call in an exception handler to ignore any exception, issue a warning, and continue."""
    logging.warning(f"Handling webdataset error ({repr(exn)}). Ignoring.")
    return True


def tarfile_to_samples_nothrow(src, handler=log_and_continue):
    # NOTE this is a re-impl of the webdataset impl with group_by_keys that doesn't throw
    streams = url_opener(src, handler=handler)
    files = tar_file_expander(streams, handler=handler)
    samples = group_by_keys_nothrow(files, handler=handler)
    return samples


def get_bytes_dataloader(shards, dl_workers=0):
    """
    returns bytes dataloader

    shards - list of shards to load from
    dl_workers - how many workers the dataloader has access to
                 if dl_workers == 0 then doesn't wrap dataset in PyTorch DataLoader
    """
    pipeline = [wds.SimpleShardList(shards)]

    pipeline.extend(
        [
            wds.split_by_node,
            wds.split_by_worker,
            tarfile_to_samples_nothrow,  # wds.tarfile_to_samples(handler=log_and_continue),
            wds.select(filter_no_caption_or_no_video),
        ]
    )

    dataloader = wds.DataPipeline(*pipeline)

    if dl_workers > 0:
        dataloader = wds.WebLoader(
            dataset,
            batch_size=None,
            num_workers=dl_workers,
            persistent_workers=True,
            prefetch_factor=8,
            pin_memory=True,
        )

    return dataloader