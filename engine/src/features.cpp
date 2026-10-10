#include <algorithm>
#include <array>
#include <btcore/features.hpp>
#include <btcore/indicators.hpp>
#include <btcore/parallel.hpp>
#include <functional>

namespace btcore {

namespace {

constexpr int kWeek = 5;
constexpr int kMonth = 21;
constexpr int kQuarter = 63;
constexpr int kHalfYear = 126;
constexpr int kYear = 252;
constexpr int kShortWindow = 20;
constexpr int kMediumWindow = 50;
constexpr int kLongWindow = 200;
constexpr int kRsiPeriod = 14;
constexpr double kBandWidth = 2.0;

// Price levels and differences of them, read in their own day's scale.
constexpr std::array kLevels{Feature::change_1d,
                             Feature::sma_20,
                             Feature::sma_50,
                             Feature::sma_200,
                             Feature::ema_20,
                             Feature::ema_50,
                             Feature::bollinger_20_upper,
                             Feature::bollinger_20_lower};

// `column(feature)` gives the part of the output holding that column of these bars.
template <typename Column>
void compute(const DailyBars& bars, Column column) {
  const std::span<const double> close = bars.close;
  change(close, 1, column(Feature::change_1d));
  simple_return(close, 1, 0, column(Feature::return_1d));
  simple_return(close, kWeek, 0, column(Feature::return_1w));
  simple_return(close, kMonth, 0, column(Feature::return_1m));
  simple_return(close, kQuarter, 0, column(Feature::return_3m));
  simple_return(close, kHalfYear, 0, column(Feature::return_6m));
  simple_return(close, kYear, 0, column(Feature::return_1y));
  simple_return(close, kYear - kMonth, kMonth, column(Feature::momentum_12_1));
  realised_volatility(close, kShortWindow, kYear, column(Feature::volatility_20d));
  rsi(close, kRsiPeriod, column(Feature::rsi_14));
  sma(bars.turnover, kShortWindow, column(Feature::adtv_20d));
  ratio_to_prior_mean(bars.volume, kShortWindow, column(Feature::volume_ratio_20d));
  percentage_of(bars.delivery, bars.volume, column(Feature::delivery_pct_1d));
  sma(column(Feature::delivery_pct_1d), kShortWindow, column(Feature::delivery_pct_20d));
  distance_from_high(close, bars.high, kYear, column(Feature::from_52w_high));
  new_extreme(bars.high, kYear, Extreme::maximum, column(Feature::is_52w_high));
  new_extreme(bars.low, kYear, Extreme::minimum, column(Feature::is_52w_low));
  sma(close, kShortWindow, column(Feature::sma_20));
  sma(close, kMediumWindow, column(Feature::sma_50));
  sma(close, kLongWindow, column(Feature::sma_200));
  ema(close, kShortWindow, column(Feature::ema_20));
  ema(close, kMediumWindow, column(Feature::ema_50));
  bollinger_bands(close, kShortWindow, kBandWidth, column(Feature::bollinger_20_upper),
                  column(Feature::bollinger_20_lower));
  for (const Feature level : kLevels) {
    const std::span<double> values = column(level);
    std::transform(values.begin(), values.end(), bars.adjustment_factor.begin(), values.begin(),
                   std::divides<>());
  }
}

void require_laid_out(const DailyBars& bars) {
  for (const std::span<const double> input :
       {bars.high, bars.low, bars.volume, bars.delivery, bars.turnover, bars.adjustment_factor}) {
    require_same_length(bars.close.size(), input.size());
  }
}

std::span<double> column_of(std::span<double> out, std::size_t length, Feature feature) {
  return out.subspan(static_cast<std::size_t>(feature) * length, length);
}

}  // namespace

void daily_features(const DailyBars& bars, std::span<double> out) {
  require_laid_out(bars);
  const std::size_t length = bars.close.size();
  require_same_length(length * feature_count, out.size());
  compute(bars, [&](Feature feature) { return column_of(out, length, feature); });
}

void daily_features(const DailyBars& bars, std::span<const std::int64_t> offsets,
                    std::span<double> out, unsigned threads) {
  const std::size_t length = bars.close.size();
  require_same_length(length * feature_count, out.size());
  const SeriesBatch batch(bars.close, offsets);
  parallel_for(batch.size(), threads, [&](std::size_t index) {
    const DailyBars series{
        batch.series(index),
        batch.input_series(bars.high, index),
        batch.input_series(bars.low, index),
        batch.input_series(bars.volume, index),
        batch.input_series(bars.delivery, index),
        batch.input_series(bars.turnover, index),
        batch.input_series(bars.adjustment_factor, index),
    };
    compute(series,
            [&](Feature feature) { return batch.series(column_of(out, length, feature), index); });
  });
}

DailyFeatureState::DailyFeatureState()
    : change_(1),
      return_1d_(1, 0),
      return_1w_(kWeek, 0),
      return_1m_(kMonth, 0),
      return_3m_(kQuarter, 0),
      return_6m_(kHalfYear, 0),
      return_1y_(kYear, 0),
      momentum_(kYear - kMonth, kMonth),
      volatility_(kShortWindow, kYear),
      rsi_(kRsiPeriod),
      turnover_average_(kShortWindow),
      volume_ratio_(kShortWindow),
      delivery_average_(kShortWindow),
      from_high_(kYear),
      new_high_(kYear, Extreme::maximum),
      new_low_(kYear, Extreme::minimum),
      sma_20_(kShortWindow),
      sma_50_(kMediumWindow),
      sma_200_(kLongWindow),
      ema_20_(kShortWindow),
      ema_50_(kMediumWindow),
      bands_(kShortWindow, kBandWidth) {}

std::array<double, feature_count> DailyFeatureState::update(const DailyBar& bar) {
  std::array<double, feature_count> row{};
  const auto set = [&row](Feature feature, double value) {
    row[static_cast<std::size_t>(feature)] = value;
  };
  const double factor = bar.adjustment_factor;
  set(Feature::change_1d, change_.update(bar.close) / factor);
  set(Feature::return_1d, return_1d_.update(bar.close));
  set(Feature::return_1w, return_1w_.update(bar.close));
  set(Feature::return_1m, return_1m_.update(bar.close));
  set(Feature::return_3m, return_3m_.update(bar.close));
  set(Feature::return_6m, return_6m_.update(bar.close));
  set(Feature::return_1y, return_1y_.update(bar.close));
  set(Feature::momentum_12_1, momentum_.update(bar.close));
  set(Feature::volatility_20d, volatility_.update(bar.close));
  set(Feature::rsi_14, rsi_.update(bar.close));
  set(Feature::adtv_20d, turnover_average_.update(bar.turnover));
  set(Feature::volume_ratio_20d, volume_ratio_.update(bar.volume));
  const double delivery_share = percentage(bar.delivery, bar.volume);
  set(Feature::delivery_pct_1d, delivery_share);
  set(Feature::delivery_pct_20d, delivery_average_.update(delivery_share));
  set(Feature::from_52w_high, from_high_.update(bar.close, bar.high));
  set(Feature::is_52w_high, new_high_.update(bar.high));
  set(Feature::is_52w_low, new_low_.update(bar.low));
  set(Feature::sma_20, sma_20_.update(bar.close) / factor);
  set(Feature::sma_50, sma_50_.update(bar.close) / factor);
  set(Feature::sma_200, sma_200_.update(bar.close) / factor);
  set(Feature::ema_20, ema_20_.update(bar.close) / factor);
  set(Feature::ema_50, ema_50_.update(bar.close) / factor);
  const Band band = bands_.update(bar.close);
  set(Feature::bollinger_20_upper, band.upper / factor);
  set(Feature::bollinger_20_lower, band.lower / factor);
  return row;
}

}  // namespace btcore
