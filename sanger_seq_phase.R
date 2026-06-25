suppressPackageStartupMessages({
  library(sangerseqR)
  library(Biostrings)
  library(pwalign)
})

# =========================
# 环境在 scRNAseq_R
# 安装一个包即可
# pak::pkg_install("sangerseqR")
# =========================

# =========================
# 使用方法
# - 把测序的到的 ab1 文件，ref_file <- "wt_grin2a_Mus_musculus_mRNA.fa" 文件，还有 代码文件全部放在一个目录
# - Rscript sanger_seq_phase.R 运行即可。参数在 sanger_seq_phase.R 内修改，不传参了
# - 结果：batch_sangerseqR_out/genotype_summary.csv 主要看这个，也可以看每个样品的拆链和比对结果
# =========================


# =========================
# 需要你改的参数
# =========================

## ref_file 必须是 fa 文件！！！！！
ab1_dir <- "."
ref_file <- "wt_grin2a_Mus_musculus_mRNA.fa"

# reference 中你关心的片段坐标，1-based，闭区间
# 例如你想看 ref 的第 1200 到 1350 bp，就写：
target_start <- 1200
target_end   <- 1350

# ==============================================
# 最好用序列，这样方便判断基因型
# 结果表格里会直接给出 target_seq 的第几位变成了什么
# =============================================

# 如果你不想用坐标，也可以直接指定目标片段序列：
# target_seq <- "ATGCGT..."
# 如果用坐标，就保持 NA
# target_seq <- NA_character_
target_seq <- "AACAACTACCCCTATATGCACCAGTACATGAC"

# sangerseqR 参数
ratio <- 0.33
trim5 <- 30
trim3 <- 30

outdir <- "batch_sangerseqR_out"
dir.create(outdir, showWarnings = FALSE, recursive = TRUE)

# =========================
# 工具函数
# =========================

clean_dna <- function(x) {
  x <- toupper(x)
  gsub("[^ACGTN]", "", x)
    
}

read_ref_sequence <- function(ref_file) {
  lines <- readLines(ref_file, warn = FALSE)

  # FASTA 格式
  if (length(lines) > 0 && startsWith(lines[1], ">")) {
    seq <- as.character(readDNAStringSet(ref_file)[[1]])
  } else {
    # 普通纯文本序列
    seq <- paste(lines, collapse = "")
  }

  clean_dna(seq)
}

make_variant_signature <- function(aligned_ref, aligned_query, coord_offset = 0) {
  r <- strsplit(aligned_ref, "")[[1]]
  q <- strsplit(aligned_query, "")[[1]]

  diff_idx <- which(r != q)

  if (length(diff_idx) == 0) {
    return("REF")
  }

  # ref 内部坐标；遇到 ref gap 时坐标不前进
  ref_pos <- cumsum(r != "-")

  vars <- character()

  for (i in diff_idx) {
    if (r[i] == "-") {
      # 插入：发生在当前 ref_pos 之后
      vars <- c(vars, sprintf("ins_after_%d:%s", coord_offset + ref_pos[i], q[i]))
    } else if (q[i] == "-") {
      # 删除
      vars <- c(vars, sprintf("%d:%s>del", coord_offset + ref_pos[i], r[i]))
    } else {
      # SNP / 替换
      vars <- c(vars, sprintf("%d:%s>%s", coord_offset + ref_pos[i], r[i], q[i]))
    }
  }

  paste(vars, collapse = ";")
}

align_once <- function(allele_seq, ref_target, direction = "+", coord_offset = 0) {
  pa <- pairwiseAlignment(
    pattern = DNAString(ref_target),
    subject = DNAString(allele_seq),
    type = "global-local"
  )

  aligned_ref <- as.character(pattern(pa))
  aligned_qry <- as.character(subject(pa))

  r <- strsplit(aligned_ref, "")[[1]]
  q <- strsplit(aligned_qry, "")[[1]]

  matches <- sum(r == q & r != "-")
  compared_cols <- sum(r != "-" | q != "-")
  identity <- ifelse(compared_cols == 0, NA_real_, matches / compared_cols)

  signature <- make_variant_signature(
    aligned_ref,
    aligned_qry,
    coord_offset = coord_offset
  )

  list(
    score = score(pa),
    identity = identity,
    variant_signature = signature,
    aligned_ref = aligned_ref,
    aligned_query = aligned_qry,
    direction = direction
  )
}

align_to_target_best_strand <- function(allele_seq, ref_target, coord_offset = 0) {
  allele_seq <- clean_dna(allele_seq)

  fwd <- align_once(
    allele_seq = allele_seq,
    ref_target = ref_target,
    direction = "+",
    coord_offset = coord_offset
  )

  rev_seq <- as.character(reverseComplement(DNAString(allele_seq)))

  rev <- align_once(
    allele_seq = rev_seq,
    ref_target = ref_target,
    direction = "-",
    coord_offset = coord_offset
  )

  if (rev$score > fwd$score) {
    return(rev)
  } else {
    return(fwd)
  }
}

classify_genotype <- function(sig1, sig2) {
  a1_ref <- identical(sig1, "REF")
  a2_ref <- identical(sig2, "REF")

  if (a1_ref && a2_ref) {
    return("homozygous_reference_or_WT")
  }

  if (identical(sig1, sig2)) {
    return("homozygous_mutant")
  }

  if (xor(a1_ref, a2_ref)) {
    return("heterozygous_ref_alt")
  }

  return("heterozygous_two_alt_or_complex")
}

process_one_ab1 <- function(ab1_file, ref_seq, ref_target, coord_offset) {
  sample_id <- tools::file_path_sans_ext(basename(ab1_file))
  message("Processing: ", sample_id)

  tryCatch({
    # 1. 读取 Sanger trace
    x <- readsangerseq(ab1_file)

    # 2. 根据峰高重新识别 primary / secondary basecalls
    x_calls <- makeBaseCalls(x, ratio = ratio)

    # 3. 根据 reference 给两条 allele 定相
    x_phase <- setAllelePhase(
      x_calls,
      refseq = ref_seq,
      trim5 = trim5,
      trim3 = trim3
    )

    # 4. 拿到两条链
    allele1 <- primarySeq(x_phase, string = TRUE)
    allele2 <- secondarySeq(x_phase, string = TRUE)

    # 5. 保存每个样本拆出的两条 allele
    allele_fa <- file.path(outdir, paste0(sample_id, ".alleles.fa"))

    writeLines(
      c(
        paste0(">", sample_id, "|allele1_reference_like"),
        allele1,
        paste0(">", sample_id, "|allele2_alternate_like"),
        allele2
      ),
      allele_fa
    )

    # 6. 保存 phased trace PDF，方便人工复核
    trace_pdf <- file.path(outdir, paste0(sample_id, ".phased_trace.pdf"))

    chromatogram(
      x_phase,
      showcalls = "both",
      width = 100,
      height = 2,
      filename = trace_pdf,
      showhets = TRUE,
      trim5 = trim5,
      trim3 = trim3
    )

    # 7. 两条 allele 分别和目标 reference 片段比对
    a1 <- align_to_target_best_strand(
      allele_seq = allele1,
      ref_target = ref_target,
      coord_offset = coord_offset
    )

    a2 <- align_to_target_best_strand(
      allele_seq = allele2,
      ref_target = ref_target,
      coord_offset = coord_offset
    )

    genotype <- classify_genotype(
      a1$variant_signature,
      a2$variant_signature
    )

    # 8. 保存目标区域比对文本
    aln_file <- file.path(outdir, paste0(sample_id, ".target_alignment.txt"))

    writeLines(
      c(
        paste0("# ", sample_id),
        paste0("# genotype: ", genotype),
        "",
        ">reference_target_vs_allele1_ref_like",
        a1$aligned_ref,
        a1$aligned_query,
        paste0("signature: ", a1$variant_signature),
        paste0("identity: ", round(a1$identity, 4)),
        paste0("strand: ", a1$direction),
        "",
        ">reference_target_vs_allele2_alt_like",
        a2$aligned_ref,
        a2$aligned_query,
        paste0("signature: ", a2$variant_signature),
        paste0("identity: ", round(a2$identity, 4)),
        paste0("strand: ", a2$direction)
      ),
      aln_file
    )

    data.frame(
      sample_id = sample_id,
      ab1_file = basename(ab1_file),
      status = "OK",
      genotype = genotype,
      allele1_signature = a1$variant_signature,
      allele2_signature = a2$variant_signature,
      allele1_identity = round(a1$identity, 4),
      allele2_identity = round(a2$identity, 4),
      allele1_strand = a1$direction,
      allele2_strand = a2$direction,
      allele_fasta = basename(allele_fa),
      trace_pdf = basename(trace_pdf),
      alignment_txt = basename(aln_file),
      stringsAsFactors = FALSE
    )

  }, error = function(e) {
    data.frame(
      sample_id = sample_id,
      ab1_file = basename(ab1_file),
      status = paste0("ERROR: ", conditionMessage(e)),
      genotype = NA_character_,
      allele1_signature = NA_character_,
      allele2_signature = NA_character_,
      allele1_identity = NA_real_,
      allele2_identity = NA_real_,
      allele1_strand = NA_character_,
      allele2_strand = NA_character_,
      allele_fasta = NA_character_,
      trace_pdf = NA_character_,
      alignment_txt = NA_character_,
      stringsAsFactors = FALSE
    )
  })
}

# =========================
# 主流程
# =========================

ref_seq <- read_ref_sequence(ref_file)

if (!is.na(target_seq)) {
  ref_target <- clean_dna(target_seq)
  coord_offset <- 0
} else {
  ref_target <- substr(ref_seq, target_start, target_end)
  coord_offset <- target_start - 1
}

if (nchar(ref_target) == 0) {
  stop("ref_target 为空，请检查 target_start / target_end 或 target_seq。")
}

ab1_files <- list.files(
  ab1_dir,
  pattern = "\\.ab1$",
  full.names = TRUE,
  ignore.case = TRUE
)

if (length(ab1_files) == 0) {
  stop("没有找到 .ab1 文件。")
}

results <- do.call(
  rbind,
  lapply(
    ab1_files,
    process_one_ab1,
    ref_seq = ref_seq,
    ref_target = ref_target,
    coord_offset = coord_offset
  )
)

summary_file <- file.path(outdir, "genotype_summary.csv")
write.csv(results, summary_file, row.names = FALSE)

message("Done.")
message("Summary: ", summary_file)
